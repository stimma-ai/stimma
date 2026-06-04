#!/usr/bin/env python3
"""
One-time dev script to convert lineart .pth models to ONNX.

Requires torch (not a runtime dependency of the app).

Source models from lllyasviel/Annotators on HuggingFace:
  - sk_model.pth  (17MB)  → lineart_realistic_fine.onnx
  - sk_model2.pth (17MB)  → lineart_realistic_coarse.onnx
  - netG.pth      (218MB) → lineart_anime.onnx

Usage:
  pip install torch huggingface_hub
  python scripts/convert_lineart_onnx.py

Output files are written to ./lineart_onnx_output/
"""

from functools import partial
from pathlib import Path

import torch
import torch.nn as nn
from huggingface_hub import hf_hub_download


# ---------------------------------------------------------------------------
# Realistic Lineart: Generator architecture
# ---------------------------------------------------------------------------

class ResidualBlock(nn.Module):
    def __init__(self, in_features: int):
        super().__init__()
        self.conv_block = nn.Sequential(
            nn.ReflectionPad2d(1),
            nn.Conv2d(in_features, in_features, 3),
            nn.InstanceNorm2d(in_features),
            nn.ReLU(inplace=True),
            nn.ReflectionPad2d(1),
            nn.Conv2d(in_features, in_features, 3),
            nn.InstanceNorm2d(in_features),
        )

    def forward(self, x):
        return x + self.conv_block(x)


class Generator(nn.Module):
    """Realistic lineart generator — matches lllyasviel's sk_model.pth state dict layout.

    The weights use separate model0-model4 stages (not one big nn.Sequential).
    """
    def __init__(self, input_nc: int, output_nc: int, n_residual_blocks: int = 3):
        super().__init__()
        # model0: Initial convolution
        self.model0 = nn.Sequential(
            nn.ReflectionPad2d(3),
            nn.Conv2d(input_nc, 64, 7),
            nn.InstanceNorm2d(64),
            nn.ReLU(inplace=True),
        )
        # model1: Downsampling (2 stages flattened)
        self.model1 = nn.Sequential(
            nn.Conv2d(64, 128, 3, stride=2, padding=1),
            nn.InstanceNorm2d(128),
            nn.ReLU(inplace=True),
            nn.Conv2d(128, 256, 3, stride=2, padding=1),
            nn.InstanceNorm2d(256),
            nn.ReLU(inplace=True),
        )
        # model2: Residual blocks
        self.model2 = nn.Sequential(
            *[ResidualBlock(256) for _ in range(n_residual_blocks)]
        )
        # model3: Upsampling (2 stages flattened)
        self.model3 = nn.Sequential(
            nn.ConvTranspose2d(256, 128, 3, stride=2, padding=1, output_padding=1),
            nn.InstanceNorm2d(128),
            nn.ReLU(inplace=True),
            nn.ConvTranspose2d(128, 64, 3, stride=2, padding=1, output_padding=1),
            nn.InstanceNorm2d(64),
            nn.ReLU(inplace=True),
        )
        # model4: Output
        self.model4 = nn.Sequential(
            nn.ReflectionPad2d(3),
            nn.Conv2d(64, output_nc, 7),
            nn.Sigmoid(),
        )

    def forward(self, x):
        x = self.model0(x)
        x = self.model1(x)
        x = self.model2(x)
        x = self.model3(x)
        x = self.model4(x)
        return x


# ---------------------------------------------------------------------------
# Anime Lineart: UnetGenerator architecture
# ---------------------------------------------------------------------------

class UnetSkipConnectionBlock(nn.Module):
    def __init__(self, outer_nc, inner_nc, input_nc=None, submodule=None,
                 outermost=False, innermost=False, norm_layer=nn.BatchNorm2d,
                 use_dropout=False):
        super().__init__()
        self.outermost = outermost
        if input_nc is None:
            input_nc = outer_nc

        use_bias = (norm_layer == nn.InstanceNorm2d) or (isinstance(norm_layer, partial) and norm_layer.func == nn.InstanceNorm2d)
        downconv = nn.Conv2d(input_nc, inner_nc, kernel_size=4, stride=2, padding=1, bias=use_bias)
        downrelu = nn.LeakyReLU(0.2, True)
        downnorm = norm_layer(inner_nc)
        uprelu = nn.ReLU(True)
        upnorm = norm_layer(outer_nc)

        if outermost:
            upconv = nn.ConvTranspose2d(inner_nc * 2, outer_nc, kernel_size=4, stride=2, padding=1)
            down = [downconv]
            up = [uprelu, upconv, nn.Tanh()]
            model = down + [submodule] + up
        elif innermost:
            upconv = nn.ConvTranspose2d(inner_nc, outer_nc, kernel_size=4, stride=2, padding=1, bias=use_bias)
            down = [downrelu, downconv]
            up = [uprelu, upconv, upnorm]
            model = down + up
        else:
            upconv = nn.ConvTranspose2d(inner_nc * 2, outer_nc, kernel_size=4, stride=2, padding=1, bias=use_bias)
            down = [downrelu, downconv, downnorm]
            up = [uprelu, upconv, upnorm]
            if use_dropout:
                model = down + [submodule] + up + [nn.Dropout(0.5)]
            else:
                model = down + [submodule] + up

        self.model = nn.Sequential(*model)

    def forward(self, x):
        if self.outermost:
            return self.model(x)
        return torch.cat([x, self.model(x)], 1)


class UnetGenerator(nn.Module):
    def __init__(self, input_nc, output_nc, num_downs, ngf=64,
                 norm_layer=nn.BatchNorm2d, use_dropout=False):
        super().__init__()
        # Build U-Net from innermost to outermost
        unet_block = UnetSkipConnectionBlock(
            ngf * 8, ngf * 8, submodule=None, norm_layer=norm_layer, innermost=True
        )
        for _ in range(num_downs - 5):
            unet_block = UnetSkipConnectionBlock(
                ngf * 8, ngf * 8, submodule=unet_block,
                norm_layer=norm_layer, use_dropout=use_dropout
            )
        unet_block = UnetSkipConnectionBlock(ngf * 4, ngf * 8, submodule=unet_block, norm_layer=norm_layer)
        unet_block = UnetSkipConnectionBlock(ngf * 2, ngf * 4, submodule=unet_block, norm_layer=norm_layer)
        unet_block = UnetSkipConnectionBlock(ngf, ngf * 2, submodule=unet_block, norm_layer=norm_layer)
        unet_block = UnetSkipConnectionBlock(
            output_nc, ngf, input_nc=input_nc, submodule=unet_block,
            outermost=True, norm_layer=norm_layer
        )
        self.model = unet_block

    def forward(self, x):
        return self.model(x)


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def _export_onnx(model, onnx_path: Path):
    """Export model to ONNX with weights embedded (single file)."""
    import onnx

    dummy = torch.randn(1, 3, 512, 512)
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {2: "height", 3: "width"}, "output": {2: "height", 3: "width"}},
        opset_version=18,
    )
    # If torch exported with external data, re-save as single file
    data_path = Path(str(onnx_path) + ".data")
    if data_path.exists():
        model_proto = onnx.load(str(onnx_path), load_external_data=True)
        onnx.save(model_proto, str(onnx_path), save_as_external_data=False)
        data_path.unlink()

    size_mb = onnx_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {onnx_path} ({size_mb:.1f} MB)")


def convert_realistic(variant: str, pth_filename: str, onnx_filename: str, output_dir: Path):
    print(f"\n--- Converting realistic lineart ({variant}) ---")
    pth_path = hf_hub_download("lllyasviel/Annotators", pth_filename)
    print(f"  Downloaded: {pth_path}")

    model = Generator(3, 1, n_residual_blocks=3)
    model.load_state_dict(torch.load(pth_path, map_location="cpu", weights_only=True))
    model.eval()

    _export_onnx(model, output_dir / onnx_filename)


def convert_anime(output_dir: Path):
    print("\n--- Converting anime lineart ---")
    pth_path = hf_hub_download("lllyasviel/Annotators", "netG.pth")
    print(f"  Downloaded: {pth_path}")

    norm_layer = partial(nn.InstanceNorm2d, affine=False, track_running_stats=False)
    model = UnetGenerator(3, 1, num_downs=8, ngf=64, norm_layer=norm_layer)

    # The netG.pth weights have a "module." prefix from DataParallel training
    state_dict = torch.load(pth_path, map_location="cpu", weights_only=True)
    state_dict = {k.removeprefix("module."): v for k, v in state_dict.items()}
    model.load_state_dict(state_dict)
    model.eval()

    _export_onnx(model, output_dir / "lineart_anime.onnx")


def main():
    output_dir = Path("lineart_onnx_output")
    output_dir.mkdir(exist_ok=True)

    convert_realistic("fine", "sk_model.pth", "lineart_realistic_fine.onnx", output_dir)
    convert_realistic("coarse", "sk_model2.pth", "lineart_realistic_coarse.onnx", output_dir)
    convert_anime(output_dir)

    print(f"\nDone! ONNX files in {output_dir}/")
    print("Upload these to your R2 bucket (stimma-models).")


if __name__ == "__main__":
    main()
