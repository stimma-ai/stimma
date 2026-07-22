# Open Source Attribution

Stimma is free software, licensed under the [GNU Affero General Public
License v3.0](LICENSE) (AGPL-3.0-only). It is built on a large body of open
source work, and we are grateful to every project listed here.

This document credits the third-party software, models, and assets that
Stimma bundles or downloads, along with their licenses. The dependency
tables are generated from the actual lockfiles and package metadata by
`scripts/generate-attribution.py`; the curated sections are maintained by
hand. Full license texts are available from each project's linked source.
If you believe anything here is inaccurate or incomplete, please open an
issue.

## Bundled runtimes and native components

| Component | What it is | License |
|---|---|---|
| [CPython](https://www.python.org/) via [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | Portable Python runtime bundled with the app | PSF-2.0 |
| [OpenSSL 3](https://www.openssl.org/) | Statically linked into the bundled Python runtime | Apache-2.0 |
| [libffi](https://sourceware.org/libffi/), [expat](https://libexpat.github.io/) | Statically linked into the bundled Python runtime | MIT |
| [zlib](https://zlib.net/), [bzip2](https://sourceware.org/bzip2/), [xz/liblzma](https://tukaani.org/xz/) | Compression libraries in the bundled Python runtime | zlib / BSD-style / 0BSD |
| [SQLite](https://sqlite.org/) | Database engine in the bundled Python runtime and app | Public domain |
| [libedit](https://thrysoee.dk/editline/), [mpdecimal](https://www.bytereef.org/mpdecimal/), [Tcl/Tk](https://www.tcl.tk/) | Support libraries in the bundled Python runtime | BSD-style |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) and [ggml](https://github.com/ggerganov/ggml) | On-device speech recognition, statically linked via whisper-rs | MIT |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | On-device speech recognition runtime | Apache-2.0 |
| [ONNX Runtime](https://onnxruntime.ai/) | ML inference engine (Python package and via sherpa-onnx) | MIT |
| [PDFium](https://pdfium.googlesource.com/pdfium/) via [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | PDF rendering; bundles FreeType, libjpeg-turbo, libpng, libtiff, OpenJPEG, ICU, LCMS, and other permissively licensed libraries — see pypdfium2's bundled `LICENSES` file | BSD-3-Clause / Apache-2.0 |

Stimma does **not** bundle FFmpeg. Video features use an FFmpeg installation
already present on your system, and the build pipeline actively verifies
that no FFmpeg or restricted codec libraries ship in the app.

## Vendored source code

| Project | Used for | License |
|---|---|---|
| [ComfyUI-Darkroom](https://github.com/jeremieLouvaert/ComfyUI-Darkroom) by Jérémie Louvaert | Darkroom-style image adjustment tools (`backend/darkroom/vendor`, exact provenance and local patches documented in that directory's `ATTRIBUTION.md`) | MIT |

## Machine-learning models

These models are downloaded on demand (from Stimma's mirror or the original
host) rather than shipped inside the app. Each remains governed by its own
license:

| Model | Author / source | Used for | License |
|---|---|---|---|
| [Whisper](https://github.com/openai/whisper) (ggml conversions via [whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp)) | OpenAI | Voice input | MIT |
| [Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) (int8 ONNX via [sherpa-onnx](https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8)) | NVIDIA NeMo | Voice input | CC-BY-4.0 |
| [SAM 3](https://github.com/facebookresearch/sam3) (ONNX export via [wkentaro/sam3-onnx-models](https://huggingface.co/wkentaro/sam3-onnx-models)) | Meta AI | Segmentation / masking | SAM License (Meta; commercial use permitted, acceptable-use restrictions apply — full text distributed with the model) |
| [AuraFace v1](https://huggingface.co/fal/AuraFace-v1) | fal.ai | Face detection and embedding | Apache-2.0 |
| [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) | HKU / TikTok | Depth estimation for guided generation | See upstream repository |
| [CLIP ViT-B/32](https://github.com/openai/CLIP) (ONNX via [onnx_clip](https://github.com/lakeraai/onnx_clip)) | OpenAI | Visual similarity indexing and search | MIT |
| [RTMPose / DWPose](https://github.com/open-mmlab/mmpose) | OpenMMLab | Pose estimation for guided generation | Apache-2.0 |
| Lineart preprocessors ([informative-drawings](https://github.com/carolineec/informative-drawings), [Anime2Sketch](https://github.com/Mukosame/Anime2Sketch) lineages used by ControlNet preprocessing) | Various | Line-art extraction for guided generation | See upstream repositories |

## Fonts

| Font | Foundry | License |
|---|---|---|
| [General Sans](https://www.fontshare.com/fonts/general-sans) | Indian Type Foundry via Fontshare | Fontshare Free Font License (free for commercial use) |

## License notes

- Several dependencies are offered under a choice of licenses. Where a
  choice exists, Stimma uses them under the following terms: **pyphen** and
  **tld** under MPL-1.1; **DOMPurify** under Apache-2.0; **r-efi** under
  MIT; all `MIT OR Apache-2.0` dual-licensed Rust crates under either
  license's terms.
- A small number of dependencies are MPL-2.0 (e.g. **certifi**, and the
  Servo-derived crates **cssparser**, **selectors**, **dtoa-short**,
  **option-ext**; parts of **tqdm**). MPL-2.0 is a file-level license;
  Stimma uses these projects unmodified, and their source is available at
  the linked upstream repositories.
- **ring** combines Apache-2.0 with ISC-style licenses inherited from
  BoringSSL; see its LICENSE file for the authoritative terms.
- The ICU4X crates (**icu_\***, **zerovec**, **yoke**, and friends) are
  licensed Unicode-3.0. **webpki-roots** embeds Mozilla's CA certificate
  bundle under CDLA-Permissive-2.0.
- **trafilatura** is Apache-2.0 as of v2.0.0 (the pinned version); earlier
  releases were GPL-3.0.

## Python packages

<!-- BEGIN GENERATED: python -->
126 packages (direct and transitive; the entire environment is bundled with the app).

| Package | Version | License | Source |
|---|---|---|---|
| aiohttp | 3.9.1 | Apache-2.0 | https://github.com/aio-libs/aiohttp |
| aiosignal | 1.4.0 | Apache-2.0 | https://github.com/aio-libs/aiosignal |
| aiosqlite | 0.19.0 | MIT | https://aiosqlite.omnilib.dev |
| alembic | 1.17.2 | MIT | https://alembic.sqlalchemy.org |
| annotated-types | 0.7.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 3.7.1 | MIT | https://github.com/agronholm/anyio |
| attrs | 25.4.0 | MIT | https://www.attrs.org/ |
| babel | 2.18.0 | BSD | https://babel.pocoo.org/ |
| bcrypt | 5.0.0 | Apache-2.0 | https://github.com/pyca/bcrypt/ |
| beautifulsoup4 | 4.14.3 | MIT | https://www.crummy.com/software/BeautifulSoup/bs4/ |
| brotli | 1.2.0 | MIT | https://github.com/google/brotli |
| brotlicffi | 1.2.0.1 | MIT | https://github.com/python-hyper/brotlicffi |
| certifi | 2025.11.12 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | 2.0.0 | MIT | https://github.com/python-cffi/cffi |
| charset-normalizer | 3.4.4 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| click | 8.3.1 | BSD-3-Clause | https://github.com/pallets/click/ |
| cmap | 0.7.0 | BSD-3-Clause | https://github.com/pyapp-kit/cmap |
| colorama | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama |
| coloredlogs | 15.0.1 | MIT | https://coloredlogs.readthedocs.io |
| courlan | 1.3.2 | Apache-2.0 | https://github.com/adbar/courlan |
| cryptography | 49.0.0 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| cssselect2 | 0.9.0 | BSD | https://doc.courtbouillon.org/cssselect2/ |
| dateparser | 1.3.0 | BSD | https://github.com/scrapinghub/dateparser |
| ddgs | 9.11.3 | MIT | https://github.com/deedy5/ddgs |
| fastapi | 0.104.1 | MIT | https://github.com/tiangolo/fastapi |
| ffmpeg-python | 0.2.0 | Apache-2.0 | https://github.com/kkroening/ffmpeg-python |
| filelock | 3.20.1 | Unlicense | https://github.com/tox-dev/py-filelock |
| flatbuffers | 25.12.19 | Apache-2.0 | https://google.github.io/flatbuffers/ |
| fonttools | 4.62.0 | MIT | http://github.com/fonttools/fonttools |
| frozenlist | 1.8.0 | Apache-2.0 | https://github.com/aio-libs/frozenlist |
| fsspec | 2026.2.0 | BSD-3-Clause | https://github.com/fsspec/filesystem_spec |
| ftfy | 6.3.1 | Apache-2.0 | https://ftfy.readthedocs.io/en/latest/ |
| future | 1.0.0 | MIT | https://python-future.org |
| gdown | 5.2.1 | MIT | https://github.com/wkentaro/gdown |
| greenlet | 3.0.1 | MIT | https://greenlet.readthedocs.io/ |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| hf-xet | 1.2.0 | Apache-2.0 | https://github.com/huggingface/xet-core |
| htmldate | 1.9.4 | Apache-2.0 | https://htmldate.readthedocs.io |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httptools | 0.7.1 | MIT | https://github.com/MagicStack/httptools |
| httpx | 0.28.1 | BSD | https://github.com/encode/httpx |
| huggingface-hub | 1.4.1 | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| humanfriendly | 10.0 | MIT | https://humanfriendly.readthedocs.io |
| idna | 3.11 | BSD-3-Clause | https://github.com/kjd/idna |
| imageio | 2.37.2 | BSD-2-Clause | https://github.com/imageio/imageio |
| imgviz | 1.8.0 | MIT | https://github.com/wkentaro/imgviz |
| jeepney | 0.9.0 | MIT | https://gitlab.com/takluyver/jeepney |
| justext | 3.0.2 | BSD | https://github.com/miso-belica/jusText |
| lazy-loader | 0.4 | BSD | https://github.com/scientific-python/lazy_loader |
| loguru | 0.7.3 | MIT | https://github.com/Delgan/loguru |
| lxml | 6.0.2 | BSD-3-Clause | https://lxml.de/ |
| lxml-html-clean | 0.4.4 | BSD-3-Clause | https://github.com/fedora-python/lxml_html_clean/ |
| mako | 1.3.10 | MIT | https://www.makotemplates.org/ |
| markdown | 3.10.1 | BSD-3-Clause | https://Python-Markdown.github.io/ |
| markdown-it-py | 4.0.0 | MIT | https://github.com/executablebooks/markdown-it-py |
| markupsafe | 3.0.3 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| mdurl | 0.1.2 | MIT | https://github.com/executablebooks/mdurl |
| mpmath | 1.3.0 | BSD | http://mpmath.org/ |
| multidict | 6.7.0 | Apache License 2.0 | https://github.com/aio-libs/multidict |
| networkx | 3.6.1 | BSD-3-Clause | https://networkx.org/ |
| numpy | 1.26.2 | BSD | https://numpy.org |
| onnx | 1.17.0 | Apache License v2.0 | https://onnx.ai/ |
| onnx-clip | 4.0.1 | MIT |  |
| onnxruntime | 1.23.2 | MIT | https://onnxruntime.ai |
| opencv-python-headless | 4.11.0.86 | Apache-2.0 | https://github.com/opencv/opencv-python |
| osam | 0.2.5 | MIT | https://github.com/wkentaro/osam |
| packaging | 25.0 | Apache-2.0 | https://github.com/pypa/packaging |
| piexif | 1.1.3 | MIT | https://github.com/hMatoba/Piexif |
| pillow | 10.4.0 | HPND | https://python-pillow.org |
| primp | 1.1.3 | MIT License | https://github.com/deedy5/primp |
| propcache | 0.4.1 | Apache-2.0 | https://github.com/aio-libs/propcache |
| protobuf | 6.33.2 | 3-Clause BSD License | https://developers.google.com/protocol-buffers/ |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pydantic | 2.5.0 | MIT | https://github.com/pydantic/pydantic |
| pydantic-core | 2.14.1 | MIT | https://github.com/pydantic/pydantic-core |
| pydantic-settings | 2.1.0 | MIT | https://github.com/pydantic/pydantic-settings |
| pydyf | 0.12.1 | BSD | https://www.courtbouillon.org/pydyf |
| pygments | 2.19.2 | BSD | https://pygments.org |
| pypdfium2 | 5.6.0 | BSD-3-Clause AND Apache-2.0 (bundles PDFium and its third-party libraries) | https://github.com/pypdfium2-team/pypdfium2 |
| pyphen | 0.17.2 | GPL-2.0+ OR LGPL-2.1+ OR MPL-1.1 (used under MPL-1.1) | https://www.courtbouillon.org/pyphen |
| pyreadline3 | 3.5.4 | BSD-3-Clause | https://github.com/pyreadline3/pyreadline3 |
| pysocks | 1.7.1 | BSD-3-Clause | https://github.com/Anorov/PySocks |
| python-dateutil | 2.9.0.post0 | BSD | https://github.com/dateutil/dateutil |
| python-dotenv | 1.2.1 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| python-frontmatter | 1.1.0 | MIT | https://github.com/eyeseast/python-frontmatter |
| python-multipart | 0.0.6 | Apache-2.0 | https://github.com/andrew-d/python-multipart |
| pytz | 2026.1.post1 | MIT | http://pythonhosted.org/pytz |
| pyyaml | 6.0.1 | MIT | https://pyyaml.org/ |
| regex | 2025.11.3 | Apache-2.0 AND CNRI-Python | https://github.com/mrabarnett/mrab-regex |
| requests | 2.32.5 | Apache-2.0 | https://requests.readthedocs.io |
| rich | 14.3.2 | MIT | https://github.com/Textualize/rich |
| ruamel-yaml | 0.19.1 | MIT | https://sourceforge.net/p/ruamel-yaml/code/ci/default/tree/ |
| scikit-image | 0.23.2 | BSD | https://scikit-image.org |
| scipy | 1.16.3 | BSD | https://scipy.org/ |
| secretstorage | 3.5.0 | BSD-3-Clause | https://github.com/mitya57/secretstorage |
| shellingham | 1.5.4 | ISC | https://github.com/sarugaku/shellingham |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| sniffio | 1.3.1 | MIT | https://github.com/python-trio/sniffio |
| soupsieve | 2.8.1 | MIT | https://github.com/facelessuser/soupsieve |
| sqlalchemy | 2.0.23 | MIT | https://www.sqlalchemy.org |
| sse-starlette | 1.8.2 | BSD | https://github.com/sysid/sse-starlette |
| starlette | 0.27.0 | BSD-3-Clause | https://github.com/encode/starlette |
| strip-markdown | 1.3 | MIT | https://github.com/D3r3k23/strip_markdown |
| structlog | 25.5.0 | MIT OR Apache-2.0 | https://www.structlog.org/ |
| sympy | 1.14.0 | BSD | https://sympy.org |
| tifffile | 2026.1.28 | BSD-3-Clause | https://www.cgohlke.com |
| tinycss2 | 1.5.1 | BSD | https://www.courtbouillon.org/tinycss2 |
| tinyhtml5 | 2.1.0 | MIT | https://github.com/CourtBouillon/tinyhtml5 |
| tld | 0.13.2 | MPL-1.1 OR GPL-2.0 OR LGPL-2.1+ (used under MPL-1.1) | https://github.com/barseghyanartur/tld/ |
| tqdm | 4.67.1 | MPL-2.0 AND MIT | https://tqdm.github.io |
| trafilatura | 2.0.0 | Apache-2.0 | https://trafilatura.readthedocs.io |
| typer-slim | 0.21.1 | MIT | https://github.com/fastapi/typer |
| typing-extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| tzdata | 2025.3 | Apache-2.0 | https://github.com/python/tzdata |
| tzlocal | 5.3.1 | MIT | https://github.com/regebro/tzlocal |
| urllib3 | 2.6.2 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| uvicorn | 0.24.0 | BSD-3-Clause | https://www.uvicorn.org/ |
| uvloop | 0.22.1 | Apache-2.0 | https://github.com/MagicStack/uvloop |
| watchfiles | 1.1.1 | MIT | https://github.com/samuelcolvin/watchfiles |
| wcwidth | 0.2.14 | MIT | https://github.com/jquast/wcwidth |
| weasyprint | 68.1 | BSD | https://weasyprint.org/ |
| webencodings | 0.5.1 | BSD | https://github.com/SimonSapin/python-webencodings |
| websockets | 12.0 | BSD | https://github.com/python-websockets/websockets |
| win32-setctime | 1.2.0 | MIT | https://github.com/Delgan/win32-setctime |
| yarl | 1.22.0 | Apache-2.0 | https://github.com/aio-libs/yarl |
| zopfli | 0.4.1 | Apache-2.0 | https://github.com/fonttools/py-zopfli |
<!-- END GENERATED: python -->

## Frontend (npm) packages

<!-- BEGIN GENERATED: npm -->
100 packages (production dependency closure bundled into the UI).

| Package | Version | License | Source |
|---|---|---|---|
| @babel/helper-string-parser | 7.27.1 | MIT | https://github.com/babel/babel |
| @babel/helper-validator-identifier | 7.28.5 | MIT | https://github.com/babel/babel |
| @babel/parser | 7.28.5 | MIT | https://github.com/babel/babel |
| @babel/types | 7.28.5 | MIT | https://github.com/babel/babel |
| @codemirror/autocomplete | 6.20.2 | MIT | https://code.haverbeke.berlin/codemirror/autocomplete |
| @codemirror/commands | 6.10.3 | MIT | https://github.com/codemirror/commands |
| @codemirror/lang-python | 6.2.1 | MIT | https://github.com/codemirror/lang-python |
| @codemirror/language | 6.12.3 | MIT | https://github.com/codemirror/language |
| @codemirror/search | 6.7.0 | MIT | https://code.haverbeke.berlin/codemirror/search |
| @codemirror/state | 6.6.0 | MIT | https://github.com/codemirror/state |
| @codemirror/view | 6.43.0 | MIT | https://code.haverbeke.berlin/codemirror/view |
| @crabnebula/tauri-plugin-drag | 2.1.0 | MIT OR Apache-2.0 | https://github.com/crabnebula-dev/drag-rs |
| @dagrejs/dagre | 3.0.0 | MIT | https://github.com/dagrejs/dagre |
| @dagrejs/graphlib | 4.0.1 | MIT | https://github.com/dagrejs/graphlib |
| @heroicons/vue | 2.2.0 | MIT | https://github.com/tailwindlabs/heroicons |
| @jridgewell/sourcemap-codec | 1.5.5 | MIT | https://github.com/jridgewell/sourcemaps |
| @lezer/common | 1.5.1 | MIT | https://github.com/lezer-parser/common |
| @lezer/highlight | 1.2.3 | MIT | https://github.com/lezer-parser/highlight |
| @lezer/lr | 1.4.8 | MIT | https://github.com/lezer-parser/lr |
| @lezer/python | 1.1.18 | MIT | https://github.com/lezer-parser/python |
| @marijn/find-cluster-break | 1.0.2 | MIT | https://github.com/marijnh/find-cluster-break |
| @replit/codemirror-vim | 6.3.0 | MIT | https://github.com/replit/codemirror-vim |
| @tailwindcss/typography | 0.5.19 | MIT | https://github.com/tailwindlabs/tailwindcss-typography |
| @tauri-apps/api | 2.10.1 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |
| @tauri-apps/plugin-clipboard-manager | 2.3.2 | MIT OR Apache-2.0 | https://github.com/tauri-apps/plugins-workspace |
| @tauri-apps/plugin-dialog | 2.5.0 | MIT OR Apache-2.0 | https://github.com/tauri-apps/plugins-workspace |
| @tauri-apps/plugin-fs | 2.4.5 | MIT OR Apache-2.0 | https://github.com/tauri-apps/plugins-workspace |
| @tauri-apps/plugin-opener | 2.5.3 | MIT OR Apache-2.0 | https://github.com/tauri-apps/plugins-workspace |
| @tauri-apps/plugin-process | 2.3.1 | MIT OR Apache-2.0 | https://github.com/tauri-apps/plugins-workspace |
| @tauri-apps/plugin-shell | 2.3.4 | MIT OR Apache-2.0 | https://github.com/tauri-apps/plugins-workspace |
| @tauri-apps/plugin-updater | 2.10.0 | MIT OR Apache-2.0 | https://github.com/tauri-apps/plugins-workspace |
| @types/web-bluetooth | 0.0.20 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @vue/compiler-core | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vue/compiler-dom | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vue/compiler-sfc | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vue/compiler-ssr | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vue/devtools-api | 6.6.4 | MIT | https://github.com/vuejs/vue-devtools |
| @vue/reactivity | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vue/runtime-core | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vue/runtime-dom | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vue/server-renderer | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vue/shared | 3.5.24 | MIT | https://github.com/vuejs/core |
| @vueuse/core | 10.11.1 | MIT | https://github.com/vueuse/vueuse |
| @vueuse/metadata | 10.11.1 | MIT | https://github.com/vueuse/vueuse |
| @vueuse/shared | 10.11.1 | MIT | https://github.com/vueuse/vueuse |
| agent-base | 6.0.2 | MIT | https://github.com/TooTallNate/node-agent-base |
| asynckit | 0.4.0 | MIT | https://github.com/alexindigo/asynckit |
| axios | 1.18.0 | MIT | https://github.com/axios/axios |
| call-bind-apply-helpers | 1.0.2 | MIT | https://github.com/ljharb/call-bind-apply-helpers |
| combined-stream | 1.0.8 | MIT | https://github.com/felixge/node-combined-stream |
| crelt | 1.0.6 | MIT | https://github.com/marijnh/crelt |
| cssesc | 3.0.0 | MIT | https://github.com/mathiasbynens/cssesc |
| csstype | 3.2.1 | MIT | https://github.com/frenic/csstype |
| debug | 4.4.3 | MIT | https://github.com/debug-js/debug |
| delayed-stream | 1.0.0 | MIT | https://github.com/felixge/node-delayed-stream |
| dompurify | 3.4.11 | (MPL-2.0 OR Apache-2.0) | https://github.com/cure53/DOMPurify |
| dunder-proto | 1.0.1 | MIT | https://github.com/es-shims/dunder-proto |
| entities | 4.5.0 | BSD-2-Clause | https://github.com/fb55/entities |
| es-define-property | 1.0.1 | MIT | https://github.com/ljharb/es-define-property |
| es-errors | 1.3.0 | MIT | https://github.com/ljharb/es-errors |
| es-object-atoms | 1.1.2 | MIT | https://github.com/ljharb/es-object-atoms |
| es-set-tostringtag | 2.1.0 | MIT | https://github.com/es-shims/es-set-tostringtag |
| estree-walker | 2.0.2 | MIT | https://github.com/Rich-Harris/estree-walker |
| follow-redirects | 1.16.0 | MIT | https://github.com/follow-redirects/follow-redirects |
| form-data | 4.0.6 | MIT | https://github.com/form-data/form-data |
| function-bind | 1.1.2 | MIT | https://github.com/Raynos/function-bind |
| get-intrinsic | 1.3.0 | MIT | https://github.com/ljharb/get-intrinsic |
| get-proto | 1.0.1 | MIT | https://github.com/ljharb/get-proto |
| gopd | 1.2.0 | MIT | https://github.com/ljharb/gopd |
| has-symbols | 1.1.0 | MIT | https://github.com/inspect-js/has-symbols |
| has-tostringtag | 1.0.2 | MIT | https://github.com/inspect-js/has-tostringtag |
| hasown | 2.0.4 | MIT | https://github.com/inspect-js/hasOwn |
| https-proxy-agent | 5.0.1 | MIT | https://github.com/TooTallNate/node-https-proxy-agent |
| magic-string | 0.30.21 | MIT | https://github.com/Rich-Harris/magic-string |
| marked | 17.0.1 | MIT | https://github.com/markedjs/marked |
| math-intrinsics | 1.1.0 | MIT | https://github.com/es-shims/math-intrinsics |
| mime-db | 1.52.0 | MIT | https://github.com/jshttp/mime-db |
| mime-types | 2.1.35 | MIT | https://github.com/jshttp/mime-types |
| mitt | 2.1.0 | MIT | https://github.com/developit/mitt |
| modern-screenshot | 4.7.0 | MIT | https://github.com/qq15725/modern-screenshot |
| ms | 2.1.3 | MIT | https://github.com/vercel/ms |
| nanoid | 3.3.15 | MIT | https://github.com/ai/nanoid |
| picocolors | 1.1.1 | ISC | https://github.com/alexeyraspopov/picocolors |
| postcss | 8.5.15 | MIT | https://github.com/postcss/postcss |
| postcss-selector-parser | 6.0.10 | MIT | https://github.com/postcss/postcss-selector-parser |
| proxy-from-env | 2.1.0 | MIT | https://github.com/Rob--W/proxy-from-env |
| ramda | 0.32.0 | MIT | https://github.com/ramda/ramda |
| rxjs | 7.8.2 | Apache-2.0 | https://github.com/reactivex/rxjs |
| source-map-js | 1.2.1 | BSD-3-Clause | https://github.com/7rulnik/source-map-js |
| style-mod | 4.1.3 | MIT | https://github.com/marijnh/style-mod |
| tslib | 2.8.1 | 0BSD | https://github.com/Microsoft/tslib |
| util-deprecate | 1.0.2 | MIT | https://github.com/TooTallNate/util-deprecate |
| vue | 3.5.24 | MIT | https://github.com/vuejs/core |
| vue-demi | 0.14.10 | MIT | https://github.com/antfu/vue-demi |
| vue-observe-visibility | 2.0.0-alpha.1 | MIT | https://github.com/Akryum/vue-observe-visibility |
| vue-resize | 2.0.0-alpha.1 | MIT | https://github.com/Akryum/vue-resize |
| vue-router | 4.6.3 | MIT | https://github.com/vuejs/router |
| vue-virtual-scroll-grid | 1.11.0 | MIT | https://github.com/rocwang/vue-virtual-scroll-grid |
| vue-virtual-scroller | 2.0.0-beta.8 | MIT | https://github.com/Akryum/vue-virtual-scroller |
| w3c-keyname | 2.2.8 | MIT | https://github.com/marijnh/w3c-keyname |
<!-- END GENERATED: npm -->

## Rust crates

<!-- BEGIN GENERATED: rust -->
575 crates (535 compiled into shipped binaries; the rest are marked build-time only).

| Crate | Version(s) | License | Source | Notes |
|---|---|---|---|---|
| adler2 | 2.0.1 | 0BSD OR MIT OR Apache-2.0 | https://github.com/oyvindln/adler2 |  |
| ahash | 0.7.8 | MIT OR Apache-2.0 | https://github.com/tkaitchuck/ahash |  |
| aho-corasick | 1.1.4 | Unlicense OR MIT | https://github.com/BurntSushi/aho-corasick |  |
| alloc-no-stdlib | 2.0.4 | BSD-3-Clause | https://github.com/dropbox/rust-alloc-no-stdlib |  |
| alloc-stdlib | 0.2.2 | BSD-3-Clause | https://github.com/dropbox/rust-alloc-no-stdlib |  |
| alsa | 0.9.1 | Apache-2.0 OR MIT | https://github.com/diwic/alsa-rs |  |
| alsa-sys | 0.3.1 | MIT | https://github.com/diwic/alsa-sys |  |
| android_log-sys | 0.3.2 | MIT OR Apache-2.0 | https://github.com/rust-mobile/android_log-sys-rs |  |
| android_logger | 0.15.1 | MIT OR Apache-2.0 | https://github.com/rust-mobile/android_logger-rs |  |
| android_system_properties | 0.1.5 | MIT OR Apache-2.0 | https://github.com/nical/android_system_properties |  |
| anyhow | 1.0.100 | MIT OR Apache-2.0 | https://github.com/dtolnay/anyhow |  |
| arbitrary | 1.4.2 | MIT OR Apache-2.0 | https://github.com/rust-fuzz/arbitrary/ |  |
| arboard | 3.6.1 | MIT OR Apache-2.0 | https://github.com/1Password/arboard |  |
| arrayvec | 0.7.6 | MIT OR Apache-2.0 | https://github.com/bluss/arrayvec |  |
| async-broadcast | 0.7.2 | MIT OR Apache-2.0 | https://github.com/smol-rs/async-broadcast |  |
| async-channel | 2.5.0 | Apache-2.0 OR MIT | https://github.com/smol-rs/async-channel |  |
| async-executor | 1.13.3 | Apache-2.0 OR MIT | https://github.com/smol-rs/async-executor |  |
| async-io | 2.6.0 | Apache-2.0 OR MIT | https://github.com/smol-rs/async-io |  |
| async-lock | 3.4.2 | Apache-2.0 OR MIT | https://github.com/smol-rs/async-lock |  |
| async-process | 2.5.0 | Apache-2.0 OR MIT | https://github.com/smol-rs/async-process |  |
| async-recursion | 1.1.1 | MIT OR Apache-2.0 | https://github.com/dcchut/async-recursion |  |
| async-signal | 0.2.13 | Apache-2.0 OR MIT | https://github.com/smol-rs/async-signal |  |
| async-task | 4.7.1 | Apache-2.0 OR MIT | https://github.com/smol-rs/async-task |  |
| async-trait | 0.1.89 | MIT OR Apache-2.0 | https://github.com/dtolnay/async-trait |  |
| atk | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| atk-sys | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| atomic-waker | 1.1.2 | Apache-2.0 OR MIT | https://github.com/smol-rs/atomic-waker |  |
| autocfg | 1.5.0 | Apache-2.0 OR MIT | https://github.com/cuviper/autocfg | build-time only |
| base64 | 0.21.7, 0.22.1 | MIT OR Apache-2.0 | https://github.com/marshallpierce/rust-base64 |  |
| bindgen | 0.69.5, 0.72.1 | BSD-3-Clause | https://github.com/rust-lang/rust-bindgen | build-time only |
| bitflags | 1.3.2, 2.10.0 | MIT OR Apache-2.0 | https://github.com/bitflags/bitflags |  |
| bitvec | 1.0.1 | MIT | https://github.com/bitvecto-rs/bitvec |  |
| block | 0.1.6 | MIT | http://github.com/SSheldon/rust-block |  |
| block-buffer | 0.10.4 | MIT OR Apache-2.0 | https://github.com/RustCrypto/utils |  |
| block2 | 0.6.2 | MIT | https://github.com/madsmtm/objc2 |  |
| blocking | 1.6.2 | Apache-2.0 OR MIT | https://github.com/smol-rs/blocking |  |
| borsh | 1.6.0 | MIT OR Apache-2.0 | https://github.com/near/borsh-rs |  |
| borsh-derive | 1.6.0 | Apache-2.0 | https://github.com/near/borsh-rs |  |
| brotli | 8.0.2 | BSD-3-Clause AND MIT | https://github.com/dropbox/rust-brotli |  |
| brotli-decompressor | 5.0.0 | BSD-3-Clause OR MIT | https://github.com/dropbox/rust-brotli-decompressor |  |
| bumpalo | 3.19.1 | MIT OR Apache-2.0 | https://github.com/fitzgen/bumpalo |  |
| byte-unit | 5.2.0 | MIT | https://github.com/magiclen/byte-unit |  |
| bytecheck | 0.6.12 | MIT | https://github.com/djkoloski/bytecheck |  |
| bytecheck_derive | 0.6.12 | MIT | https://github.com/djkoloski/bytecheck |  |
| bytemuck | 1.24.0 | Zlib OR Apache-2.0 OR MIT | https://github.com/Lokathor/bytemuck |  |
| byteorder | 1.5.0 | Unlicense OR MIT | https://github.com/BurntSushi/byteorder |  |
| byteorder-lite | 0.1.0 | Unlicense OR MIT | https://github.com/image-rs/byteorder-lite |  |
| bytes | 1.11.0 | MIT | https://github.com/tokio-rs/bytes |  |
| bzip2 | 0.4.4 | MIT OR Apache-2.0 | https://github.com/alexcrichton/bzip2-rs | build-time only |
| bzip2-sys | 0.1.13+1.0.8 | MIT OR Apache-2.0 | https://github.com/alexcrichton/bzip2-rs | build-time only |
| cairo-rs | 0.18.5 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| cairo-sys-rs | 0.18.2 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| camino | 1.2.2 | MIT OR Apache-2.0 | https://github.com/camino-rs/camino |  |
| cargo-platform | 0.1.9 | MIT OR Apache-2.0 | https://github.com/rust-lang/cargo |  |
| cargo_metadata | 0.19.2 | MIT | https://github.com/oli-obk/cargo_metadata |  |
| cargo_toml | 0.22.3 | Apache-2.0 OR MIT | https://gitlab.com/lib.rs/cargo_toml | build-time only |
| cc | 1.2.50 | MIT OR Apache-2.0 | https://github.com/rust-lang/cc-rs | build-time only |
| cesu8 | 1.1.0 | Apache-2.0 OR MIT | https://github.com/emk/cesu8-rs |  |
| cexpr | 0.6.0 | Apache-2.0 OR MIT | https://github.com/jethrogb/rust-cexpr | build-time only |
| cfb | 0.7.3 | MIT | https://github.com/mdsteele/rust-cfb |  |
| cfg-expr | 0.15.8 | MIT OR Apache-2.0 | https://github.com/EmbarkStudios/cfg-expr | build-time only |
| cfg-if | 1.0.4 | MIT OR Apache-2.0 | https://github.com/rust-lang/cfg-if |  |
| cfg_aliases | 0.2.1 | MIT | https://github.com/katharostech/cfg_aliases | build-time only |
| chrono | 0.4.42 | MIT OR Apache-2.0 | https://github.com/chronotope/chrono |  |
| clang-sys | 1.8.1 | Apache-2.0 | https://github.com/KyleMayes/clang-sys | build-time only |
| clipboard-win | 5.4.1 | BSL-1.0 | https://github.com/DoumanAsh/clipboard-win |  |
| cmake | 0.1.58 | MIT OR Apache-2.0 | https://github.com/rust-lang/cmake-rs | build-time only |
| cocoa | 0.26.1 | MIT OR Apache-2.0 | https://github.com/servo/core-foundation-rs |  |
| cocoa-foundation | 0.2.1 | MIT OR Apache-2.0 | https://github.com/servo/core-foundation-rs |  |
| combine | 4.6.7 | MIT | https://github.com/Marwes/combine |  |
| concurrent-queue | 2.5.0 | Apache-2.0 OR MIT | https://github.com/smol-rs/concurrent-queue |  |
| convert_case | 0.4.0 | MIT | https://github.com/rutrum/convert-case |  |
| cookie | 0.18.1 | MIT OR Apache-2.0 | https://github.com/SergioBenitez/cookie-rs |  |
| core-foundation | 0.10.1 | MIT OR Apache-2.0 | https://github.com/servo/core-foundation-rs |  |
| core-foundation-sys | 0.8.7 | MIT OR Apache-2.0 | https://github.com/servo/core-foundation-rs |  |
| core-graphics | 0.24.0 | MIT OR Apache-2.0 | https://github.com/servo/core-foundation-rs |  |
| core-graphics-types | 0.2.0 | MIT OR Apache-2.0 | https://github.com/servo/core-foundation-rs |  |
| coreaudio-rs | 0.11.3 | MIT OR Apache-2.0 | https://github.com/RustAudio/coreaudio-rs |  |
| coreaudio-sys | 0.2.17 | MIT | https://github.com/RustAudio/coreaudio-sys |  |
| cpal | 0.15.3 | Apache-2.0 | https://github.com/rustaudio/cpal |  |
| cpufeatures | 0.2.17 | MIT OR Apache-2.0 | https://github.com/RustCrypto/utils |  |
| crc32fast | 1.5.0 | MIT OR Apache-2.0 | https://github.com/srijs/rust-crc32fast |  |
| crossbeam-channel | 0.5.15 | MIT OR Apache-2.0 | https://github.com/crossbeam-rs/crossbeam |  |
| crossbeam-utils | 0.8.21 | MIT OR Apache-2.0 | https://github.com/crossbeam-rs/crossbeam |  |
| crunchy | 0.2.4 | MIT | https://github.com/eira-fransham/crunchy |  |
| crypto-common | 0.1.7 | MIT OR Apache-2.0 | https://github.com/RustCrypto/traits |  |
| cssparser | 0.29.6 | MPL-2.0 | https://github.com/servo/rust-cssparser |  |
| cssparser-macros | 0.6.1 | MPL-2.0 | https://github.com/servo/rust-cssparser |  |
| ctor | 0.2.9 | Apache-2.0 OR MIT | https://github.com/mmastrac/rust-ctor |  |
| darling | 0.21.3 | MIT | https://github.com/TedDriggs/darling |  |
| darling_core | 0.21.3 | MIT | https://github.com/TedDriggs/darling |  |
| darling_macro | 0.21.3 | MIT | https://github.com/TedDriggs/darling |  |
| dasp_sample | 0.11.0 | MIT OR Apache-2.0 | https://github.com/rustaudio/sample |  |
| deranged | 0.5.5 | MIT OR Apache-2.0 | https://github.com/jhpratt/deranged |  |
| derive_arbitrary | 1.4.2 | MIT OR Apache-2.0 | https://github.com/rust-fuzz/arbitrary |  |
| derive_more | 0.99.20 | MIT | https://github.com/JelteF/derive_more |  |
| digest | 0.10.7 | MIT OR Apache-2.0 | https://github.com/RustCrypto/traits |  |
| dirs | 6.0.0 | MIT OR Apache-2.0 | https://github.com/soc/dirs-rs |  |
| dirs-sys | 0.5.0 | MIT OR Apache-2.0 | https://github.com/dirs-dev/dirs-sys-rs |  |
| dispatch | 0.2.0 | MIT | http://github.com/SSheldon/rust-dispatch |  |
| dispatch2 | 0.3.0 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| displaydoc | 0.2.5 | MIT OR Apache-2.0 | https://github.com/yaahc/displaydoc |  |
| dlopen2 | 0.8.2 | MIT | https://github.com/OpenByteDev/dlopen2 |  |
| dlopen2_derive | 0.4.3 | MIT | https://github.com/OpenByteDev/dlopen2 |  |
| downcast-rs | 1.2.1 | MIT OR Apache-2.0 | https://github.com/marcianx/downcast-rs |  |
| dpi | 0.1.2 | Apache-2.0 AND MIT | https://github.com/rust-windowing/winit |  |
| drag | 2.1.0 | Apache-2.0 OR MIT |  |  |
| dtoa | 1.0.10 | MIT OR Apache-2.0 | https://github.com/dtolnay/dtoa |  |
| dtoa-short | 0.3.5 | MPL-2.0 | https://github.com/upsuper/dtoa-short |  |
| dunce | 1.0.5 | CC0-1.0 OR MIT-0 OR Apache-2.0 | https://gitlab.com/kornelski/dunce |  |
| dyn-clone | 1.0.20 | MIT OR Apache-2.0 | https://github.com/dtolnay/dyn-clone |  |
| either | 1.16.0 | MIT OR Apache-2.0 | https://github.com/rayon-rs/either | build-time only |
| embed-resource | 3.0.6 | MIT | https://github.com/nabijaczleweli/rust-embed-resource | build-time only |
| embed_plist | 1.2.2 | MIT OR Apache-2.0 | https://github.com/nvzqz/embed-plist-rs |  |
| encoding_rs | 0.8.35 | (Apache-2.0 OR MIT) AND BSD-3-Clause | https://github.com/hsivonen/encoding_rs |  |
| endi | 1.1.1 | MIT | https://github.com/zeenix/endi |  |
| enumflags2 | 0.7.12 | MIT OR Apache-2.0 | https://github.com/meithecatte/enumflags2 |  |
| enumflags2_derive | 0.7.12 | MIT OR Apache-2.0 | https://github.com/meithecatte/enumflags2 |  |
| env_filter | 0.1.4 | MIT OR Apache-2.0 | https://github.com/rust-cli/env_logger |  |
| equivalent | 1.0.2 | Apache-2.0 OR MIT | https://github.com/indexmap-rs/equivalent |  |
| erased-serde | 0.4.9 | MIT OR Apache-2.0 | https://github.com/dtolnay/erased-serde |  |
| errno | 0.3.14 | MIT OR Apache-2.0 | https://github.com/lambda-fairy/rust-errno |  |
| error-code | 3.3.2 | BSL-1.0 | https://github.com/DoumanAsh/error-code |  |
| event-listener | 5.4.1 | Apache-2.0 OR MIT | https://github.com/smol-rs/event-listener |  |
| event-listener-strategy | 0.5.4 | Apache-2.0 OR MIT | https://github.com/smol-rs/event-listener-strategy |  |
| fastrand | 2.3.0 | Apache-2.0 OR MIT | https://github.com/smol-rs/fastrand |  |
| fax | 0.2.6 | MIT | https://github.com/pdf-rs/fax |  |
| fax_derive | 0.2.0 | MIT | https://github.com/pdf-rs/fax |  |
| fdeflate | 0.3.7 | MIT OR Apache-2.0 | https://github.com/image-rs/fdeflate |  |
| fern | 0.7.1 | MIT | https://github.com/daboross/fern |  |
| field-offset | 0.3.6 | MIT OR Apache-2.0 | https://github.com/Diggsey/rust-field-offset |  |
| filetime | 0.2.27 | MIT OR Apache-2.0 | https://github.com/alexcrichton/filetime |  |
| find-msvc-tools | 0.1.5 | MIT OR Apache-2.0 | https://github.com/rust-lang/cc-rs | build-time only |
| fixedbitset | 0.5.7 | MIT OR Apache-2.0 | https://github.com/petgraph/fixedbitset |  |
| flate2 | 1.1.5 | MIT OR Apache-2.0 | https://github.com/rust-lang/flate2-rs |  |
| fnv | 1.0.7 | Apache-2.0  OR  MIT | https://github.com/servo/rust-fnv |  |
| foldhash | 0.1.5 | Zlib | https://github.com/orlp/foldhash |  |
| foreign-types | 0.5.0 | MIT OR Apache-2.0 | https://github.com/sfackler/foreign-types |  |
| foreign-types-macros | 0.2.3 | MIT OR Apache-2.0 | https://github.com/sfackler/foreign-types |  |
| foreign-types-shared | 0.3.1 | MIT OR Apache-2.0 | https://github.com/sfackler/foreign-types |  |
| form_urlencoded | 1.2.2 | MIT OR Apache-2.0 | https://github.com/servo/rust-url |  |
| fs_extra | 1.3.0 | MIT | https://github.com/webdesus/fs_extra | build-time only |
| funty | 2.0.0 | MIT | https://github.com/myrrlyn/funty |  |
| futf | 0.1.5 | MIT  OR  Apache-2.0 | https://github.com/servo/futf |  |
| futures-channel | 0.3.31 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-core | 0.3.31 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-executor | 0.3.31 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-io | 0.3.31 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-lite | 2.6.1 | Apache-2.0 OR MIT | https://github.com/smol-rs/futures-lite |  |
| futures-macro | 0.3.31 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-sink | 0.3.31 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-task | 0.3.31 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-util | 0.3.31 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| fxhash | 0.2.1 | Apache-2.0 OR MIT | https://github.com/cbreeden/fxhash |  |
| gdk | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| gdk-pixbuf | 0.18.5 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| gdk-pixbuf-sys | 0.18.0 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| gdk-sys | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| gdkwayland-sys | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| gdkx11 | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| gdkx11-sys | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| generic-array | 0.14.7 | MIT | https://github.com/fizyk20/generic-array |  |
| gethostname | 1.1.0 | Apache-2.0 | https://codeberg.org/swsnr/gethostname.rs |  |
| getrandom | 0.1.16, 0.2.16, 0.3.4 | MIT OR Apache-2.0 | https://github.com/rust-random/getrandom |  |
| gio | 0.18.4 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| gio-sys | 0.18.1 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| glib | 0.18.5 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| glib-macros | 0.18.5 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| glib-sys | 0.18.1 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| glob | 0.3.3 | MIT OR Apache-2.0 | https://github.com/rust-lang/glob |  |
| gobject-sys | 0.18.0 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| gtk | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| gtk-sys | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| gtk3-macros | 0.18.2 | MIT | https://github.com/gtk-rs/gtk3-rs |  |
| half | 2.7.1 | MIT OR Apache-2.0 | https://github.com/VoidStarKat/half-rs |  |
| hashbrown | 0.12.3, 0.15.5, 0.16.1 | MIT OR Apache-2.0 | https://github.com/rust-lang/hashbrown |  |
| heck | 0.4.1, 0.5.0 | MIT OR Apache-2.0 | https://github.com/withoutboats/heck |  |
| hermit-abi | 0.5.2 | MIT OR Apache-2.0 | https://github.com/hermit-os/hermit-rs |  |
| hex | 0.4.3 | MIT OR Apache-2.0 | https://github.com/KokaKiwi/rust-hex |  |
| home | 0.5.12 | MIT OR Apache-2.0 | https://github.com/rust-lang/cargo | build-time only |
| html5ever | 0.29.1 | MIT OR Apache-2.0 | https://github.com/servo/html5ever |  |
| http | 1.4.0 | MIT OR Apache-2.0 | https://github.com/hyperium/http |  |
| http-body | 1.0.1 | MIT | https://github.com/hyperium/http-body |  |
| http-body-util | 0.1.3 | MIT | https://github.com/hyperium/http-body |  |
| httparse | 1.10.1 | MIT OR Apache-2.0 | https://github.com/seanmonstar/httparse |  |
| hyper | 1.8.1 | MIT | https://github.com/hyperium/hyper |  |
| hyper-rustls | 0.27.7 | Apache-2.0 OR ISC OR MIT | https://github.com/rustls/hyper-rustls |  |
| hyper-util | 0.1.19 | MIT | https://github.com/hyperium/hyper-util |  |
| iana-time-zone | 0.1.64 | MIT OR Apache-2.0 | https://github.com/strawlab/iana-time-zone |  |
| iana-time-zone-haiku | 0.1.2 | MIT OR Apache-2.0 | https://github.com/strawlab/iana-time-zone |  |
| ico | 0.5.0 | MIT | https://github.com/mdsteele/rust-ico |  |
| icu_collections | 2.1.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_locale_core | 2.1.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_normalizer | 2.1.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_normalizer_data | 2.1.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_properties | 2.1.2 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_properties_data | 2.1.2 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_provider | 2.1.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| ident_case | 1.0.1 | MIT OR Apache-2.0 | https://github.com/TedDriggs/ident_case |  |
| idna | 1.1.0 | MIT OR Apache-2.0 | https://github.com/servo/rust-url/ |  |
| idna_adapter | 1.2.1 | Apache-2.0 OR MIT | https://github.com/hsivonen/idna_adapter |  |
| image | 0.25.9 | MIT OR Apache-2.0 | https://github.com/image-rs/image |  |
| indexmap | 1.9.3, 2.12.1 | Apache-2.0 OR MIT | https://github.com/indexmap-rs/indexmap |  |
| infer | 0.19.0 | MIT | https://github.com/bojand/infer |  |
| ipnet | 2.11.0 | MIT OR Apache-2.0 | https://github.com/krisprice/ipnet |  |
| iri-string | 0.7.9 | MIT OR Apache-2.0 | https://github.com/lo48576/iri-string |  |
| is-docker | 0.2.0 | MIT | https://github.com/TheLarkInn/is-docker |  |
| is-wsl | 0.4.0 | MIT | https://github.com/TheLarkInn/is-wsl |  |
| itertools | 0.12.1, 0.13.0 | MIT OR Apache-2.0 | https://github.com/rust-itertools/itertools | build-time only |
| itoa | 1.0.16 | MIT OR Apache-2.0 | https://github.com/dtolnay/itoa |  |
| javascriptcore-rs | 1.1.2 | MIT | https://github.com/tauri-apps/javascriptcore-rs |  |
| javascriptcore-rs-sys | 1.1.1 | MIT | https://github.com/tauri-apps/javascriptcore-rs |  |
| jni | 0.21.1 | MIT OR Apache-2.0 | https://github.com/jni-rs/jni-rs |  |
| jni-sys | 0.3.0 | MIT OR Apache-2.0 | https://github.com/sfackler/rust-jni-sys |  |
| jobserver | 0.1.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/jobserver-rs | build-time only |
| js-sys | 0.3.85 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/js-sys |  |
| json-patch | 3.0.1 | MIT OR Apache-2.0 | https://github.com/idubrov/json-patch |  |
| jsonptr | 0.6.3 | MIT OR Apache-2.0 | https://github.com/chanced/jsonptr |  |
| keyboard-types | 0.7.0 | MIT OR Apache-2.0 | https://github.com/pyfisch/keyboard-types |  |
| kuchikiki | 0.8.8-speedreader | MIT | https://github.com/brave/kuchikiki |  |
| lazy_static | 1.5.0 | MIT OR Apache-2.0 | https://github.com/rust-lang-nursery/lazy-static.rs |  |
| lazycell | 1.3.0 | MIT OR Apache-2.0 | https://github.com/indiv0/lazycell | build-time only |
| libappindicator | 0.9.0 | Apache-2.0 OR MIT |  |  |
| libappindicator-sys | 0.9.0 | Apache-2.0 OR MIT |  |  |
| libc | 0.2.178 | MIT OR Apache-2.0 | https://github.com/rust-lang/libc |  |
| libloading | 0.7.4, 0.8.9 | ISC | https://github.com/nagisa/rust_libloading/ |  |
| libredox | 0.1.11 | MIT | https://gitlab.redox-os.org/redox-os/libredox |  |
| linux-raw-sys | 0.11.0, 0.4.15 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/sunfishcode/linux-raw-sys |  |
| litemap | 0.8.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| lock_api | 0.4.14 | MIT OR Apache-2.0 | https://github.com/Amanieu/parking_lot |  |
| log | 0.4.29 | MIT OR Apache-2.0 | https://github.com/rust-lang/log |  |
| lru-slab | 0.1.2 | MIT OR Apache-2.0 OR Zlib | https://github.com/Ralith/lru-slab |  |
| mac | 0.1.1 | MIT OR Apache-2.0 | https://github.com/reem/rust-mac |  |
| mach2 | 0.4.3 | BSD-2-Clause OR MIT OR Apache-2.0 | https://github.com/JohnTitor/mach2 |  |
| malloc_buf | 0.0.6 | MIT | https://github.com/SSheldon/malloc_buf |  |
| markup5ever | 0.14.1 | MIT OR Apache-2.0 | https://github.com/servo/html5ever |  |
| match_token | 0.1.0 | MIT OR Apache-2.0 | https://github.com/servo/html5ever |  |
| matches | 0.1.10 | MIT | https://github.com/SimonSapin/rust-std-candidates |  |
| memchr | 2.7.6 | Unlicense OR MIT | https://github.com/BurntSushi/memchr |  |
| memoffset | 0.9.1 | MIT | https://github.com/Gilnaa/memoffset |  |
| mime | 0.3.17 | MIT OR Apache-2.0 | https://github.com/hyperium/mime |  |
| minimal-lexical | 0.2.1 | MIT OR Apache-2.0 | https://github.com/Alexhuszagh/minimal-lexical | build-time only |
| minisign-verify | 0.2.4 | MIT | https://github.com/jedisct1/rust-minisign-verify |  |
| miniz_oxide | 0.8.9 | MIT OR Zlib OR Apache-2.0 | https://github.com/Frommi/miniz_oxide/tree/master/miniz_oxide |  |
| mio | 1.1.1 | MIT | https://github.com/tokio-rs/mio |  |
| moxcms | 0.7.11 | BSD-3-Clause OR Apache-2.0 | https://github.com/awxkee/moxcms |  |
| muda | 0.17.1 | Apache-2.0 OR MIT | https://github.com/amrbashir/muda |  |
| ndk | 0.8.0, 0.9.0 | MIT OR Apache-2.0 | https://github.com/rust-mobile/ndk |  |
| ndk-context | 0.1.1 | MIT OR Apache-2.0 | https://github.com/rust-windowing/android-ndk-rs |  |
| ndk-sys | 0.5.0+25.2.9519653, 0.6.0+11769913 | MIT OR Apache-2.0 | https://github.com/rust-mobile/ndk |  |
| new_debug_unreachable | 1.0.6 | MIT | https://github.com/mbrubeck/rust-debug-unreachable |  |
| nodrop | 0.1.14 | MIT OR Apache-2.0 | https://github.com/bluss/arrayvec |  |
| nom | 7.1.3, 8.0.0 | MIT | https://github.com/rust-bakery/nom |  |
| num-conv | 0.1.0 | MIT OR Apache-2.0 | https://github.com/jhpratt/num-conv |  |
| num-derive | 0.4.2 | MIT OR Apache-2.0 | https://github.com/rust-num/num-derive |  |
| num-traits | 0.2.19 | MIT OR Apache-2.0 | https://github.com/rust-num/num-traits |  |
| num_enum | 0.7.5 | BSD-3-Clause OR MIT OR Apache-2.0 | https://github.com/illicitonion/num_enum |  |
| num_enum_derive | 0.7.5 | BSD-3-Clause OR MIT OR Apache-2.0 | https://github.com/illicitonion/num_enum |  |
| num_threads | 0.1.7 | MIT OR Apache-2.0 | https://github.com/jhpratt/num_threads |  |
| objc | 0.2.7 | MIT | http://github.com/SSheldon/rust-objc |  |
| objc2 | 0.6.3 | MIT | https://github.com/madsmtm/objc2 |  |
| objc2-app-kit | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-cloud-kit | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-core-data | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-core-foundation | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-core-graphics | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-core-image | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-core-text | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-core-video | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-encode | 4.1.0 | MIT | https://github.com/madsmtm/objc2 |  |
| objc2-exception-helper | 0.1.1 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-foundation | 0.3.2 | MIT | https://github.com/madsmtm/objc2 |  |
| objc2-io-surface | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-javascript-core | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-osa-kit | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-quartz-core | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-security | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-ui-kit | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| objc2-web-kit | 0.3.2 | Zlib OR Apache-2.0 OR MIT | https://github.com/madsmtm/objc2 |  |
| oboe | 0.6.1 | Apache-2.0 | https://github.com/katyo/oboe-rs |  |
| oboe-sys | 0.6.1 | Apache-2.0 | https://github.com/katyo/oboe-rs |  |
| once_cell | 1.21.3 | MIT OR Apache-2.0 | https://github.com/matklad/once_cell |  |
| open | 5.3.3 | MIT | https://github.com/Byron/open-rs |  |
| openssl-probe | 0.2.1 | MIT OR Apache-2.0 | https://github.com/rustls/openssl-probe |  |
| option-ext | 0.2.0 | MPL-2.0 | https://github.com/soc/option-ext |  |
| ordered-stream | 0.2.0 | MIT OR Apache-2.0 | https://github.com/danieldg/ordered-stream |  |
| os_pipe | 1.2.3 | MIT | https://github.com/oconnor663/os_pipe.rs |  |
| osakit | 0.3.1 | MIT OR Apache-2.0 | https://github.com/mdevils/rust-osakit |  |
| pango | 0.18.3 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| pango-sys | 0.18.0 | MIT | https://github.com/gtk-rs/gtk-rs-core |  |
| parking | 2.2.1 | Apache-2.0 OR MIT | https://github.com/smol-rs/parking |  |
| parking_lot | 0.12.5 | MIT OR Apache-2.0 | https://github.com/Amanieu/parking_lot |  |
| parking_lot_core | 0.9.12 | MIT OR Apache-2.0 | https://github.com/Amanieu/parking_lot |  |
| pathdiff | 0.2.3 | MIT OR Apache-2.0 | https://github.com/Manishearth/pathdiff |  |
| percent-encoding | 2.3.2 | MIT OR Apache-2.0 | https://github.com/servo/rust-url/ |  |
| petgraph | 0.8.3 | MIT OR Apache-2.0 | https://github.com/petgraph/petgraph |  |
| phf | 0.10.1, 0.11.3, 0.8.0 | MIT | https://github.com/sfackler/rust-phf |  |
| phf_codegen | 0.11.3, 0.8.0 | MIT | https://github.com/sfackler/rust-phf | build-time only |
| phf_generator | 0.10.0, 0.11.3, 0.8.0 | MIT | https://github.com/sfackler/rust-phf |  |
| phf_macros | 0.10.0, 0.11.3 | MIT | https://github.com/rust-phf/rust-phf |  |
| phf_shared | 0.10.0, 0.11.3, 0.8.0 | MIT | https://github.com/sfackler/rust-phf |  |
| pin-project-lite | 0.2.16 | Apache-2.0 OR MIT | https://github.com/taiki-e/pin-project-lite |  |
| pin-utils | 0.1.0 | MIT OR Apache-2.0 | https://github.com/rust-lang-nursery/pin-utils |  |
| piper | 0.2.4 | MIT OR Apache-2.0 | https://github.com/smol-rs/piper |  |
| pkg-config | 0.3.32 | MIT OR Apache-2.0 | https://github.com/rust-lang/pkg-config-rs | build-time only |
| plist | 1.8.0 | MIT | https://github.com/ebarnard/rust-plist/ |  |
| png | 0.17.16, 0.18.0 | MIT OR Apache-2.0 | https://github.com/image-rs/image-png |  |
| polling | 3.11.0 | Apache-2.0 OR MIT | https://github.com/smol-rs/polling |  |
| potential_utf | 0.1.4 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| powerfmt | 0.2.0 | MIT OR Apache-2.0 | https://github.com/jhpratt/powerfmt |  |
| ppv-lite86 | 0.2.21 | MIT OR Apache-2.0 | https://github.com/cryptocorrosion/cryptocorrosion |  |
| precomputed-hash | 0.1.1 | MIT | https://github.com/emilio/precomputed-hash |  |
| prettyplease | 0.2.37 | MIT OR Apache-2.0 | https://github.com/dtolnay/prettyplease | build-time only |
| proc-macro-crate | 1.3.1, 2.0.2, 3.4.0 | MIT OR Apache-2.0 | https://github.com/bkchr/proc-macro-crate |  |
| proc-macro-error | 1.0.4 | MIT OR Apache-2.0 | https://gitlab.com/CreepySkeleton/proc-macro-error |  |
| proc-macro-error-attr | 1.0.4 | MIT OR Apache-2.0 | https://gitlab.com/CreepySkeleton/proc-macro-error |  |
| proc-macro-hack | 0.5.20+deprecated | MIT OR Apache-2.0 | https://github.com/dtolnay/proc-macro-hack |  |
| proc-macro2 | 1.0.103 | MIT OR Apache-2.0 | https://github.com/dtolnay/proc-macro2 |  |
| ptr_meta | 0.1.4 | MIT | https://github.com/djkoloski/ptr_meta |  |
| ptr_meta_derive | 0.1.4 | MIT | https://github.com/djkoloski/ptr_meta |  |
| pxfm | 0.1.27 | BSD-3-Clause OR Apache-2.0 | https://github.com/awxkee/pxfm |  |
| quick-error | 2.0.1 | MIT OR Apache-2.0 | http://github.com/tailhook/quick-error |  |
| quick-xml | 0.38.4 | MIT | https://github.com/tafia/quick-xml |  |
| quinn | 0.11.9 | MIT OR Apache-2.0 | https://github.com/quinn-rs/quinn |  |
| quinn-proto | 0.11.14 | MIT OR Apache-2.0 | https://github.com/quinn-rs/quinn |  |
| quinn-udp | 0.5.14 | MIT OR Apache-2.0 | https://github.com/quinn-rs/quinn |  |
| quote | 1.0.42 | MIT OR Apache-2.0 | https://github.com/dtolnay/quote |  |
| r-efi | 5.3.0 | MIT OR Apache-2.0 OR LGPL-2.1-or-later | https://github.com/r-efi/r-efi |  |
| radium | 0.7.0 | MIT | https://github.com/bitvecto-rs/radium |  |
| rand | 0.7.3, 0.8.5, 0.9.4 | MIT OR Apache-2.0 | https://github.com/rust-random/rand |  |
| rand_chacha | 0.2.2, 0.3.1, 0.9.0 | MIT OR Apache-2.0 | https://github.com/rust-random/rand |  |
| rand_core | 0.5.1, 0.6.4, 0.9.5 | MIT OR Apache-2.0 | https://github.com/rust-random/rand |  |
| rand_hc | 0.2.0 | MIT OR Apache-2.0 | https://github.com/rust-random/rand | build-time only |
| rand_pcg | 0.2.1 | MIT OR Apache-2.0 | https://github.com/rust-random/rand | build-time only |
| raw-window-handle | 0.6.2 | MIT OR Apache-2.0 OR Zlib | https://github.com/rust-windowing/raw-window-handle |  |
| redox_syscall | 0.5.18, 0.6.0 | MIT | https://gitlab.redox-os.org/redox-os/syscall |  |
| redox_users | 0.5.2 | MIT | https://gitlab.redox-os.org/redox-os/users |  |
| ref-cast | 1.0.25 | MIT OR Apache-2.0 | https://github.com/dtolnay/ref-cast |  |
| ref-cast-impl | 1.0.25 | MIT OR Apache-2.0 | https://github.com/dtolnay/ref-cast |  |
| regex | 1.12.2 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |  |
| regex-automata | 0.4.13 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |  |
| regex-syntax | 0.8.8 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |  |
| rend | 0.4.2 | MIT | https://github.com/djkoloski/rend |  |
| reqwest | 0.12.28, 0.13.2 | MIT OR Apache-2.0 | https://github.com/seanmonstar/reqwest |  |
| rfd | 0.16.0 | MIT | https://github.com/PolyMeilex/rfd |  |
| ring | 0.17.14 | Apache-2.0 AND ISC | https://github.com/briansmith/ring |  |
| rkyv | 0.7.45 | MIT | https://github.com/rkyv/rkyv |  |
| rkyv_derive | 0.7.45 | MIT | https://github.com/rkyv/rkyv |  |
| rust_decimal | 1.39.0 | MIT | https://github.com/paupino/rust-decimal |  |
| rustc-hash | 1.1.0, 2.1.2 | Apache-2.0 OR MIT | https://github.com/rust-lang/rustc-hash |  |
| rustc_version | 0.4.1 | MIT OR Apache-2.0 | https://github.com/djc/rustc-version-rs | build-time only |
| rustix | 0.38.44, 1.1.3 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/bytecodealliance/rustix |  |
| rustls | 0.23.36 | Apache-2.0 OR ISC OR MIT | https://github.com/rustls/rustls |  |
| rustls-native-certs | 0.8.3 | Apache-2.0 OR ISC OR MIT | https://github.com/rustls/rustls-native-certs |  |
| rustls-pki-types | 1.14.0 | MIT OR Apache-2.0 | https://github.com/rustls/pki-types |  |
| rustls-platform-verifier | 0.6.2 | MIT OR Apache-2.0 | https://github.com/rustls/rustls-platform-verifier |  |
| rustls-platform-verifier-android | 0.1.1 | MIT OR Apache-2.0 | https://github.com/rustls/rustls-platform-verifier |  |
| rustls-webpki | 0.103.9 | ISC | https://github.com/rustls/webpki |  |
| rustversion | 1.0.22 | MIT OR Apache-2.0 | https://github.com/dtolnay/rustversion |  |
| ryu | 1.0.21 | Apache-2.0 OR BSL-1.0 | https://github.com/dtolnay/ryu |  |
| same-file | 1.0.6 | Unlicense OR MIT | https://github.com/BurntSushi/same-file |  |
| schannel | 0.1.28 | MIT | https://github.com/steffengy/schannel-rs |  |
| schemars | 0.8.22, 0.9.0, 1.1.0 | MIT | https://github.com/GREsau/schemars |  |
| schemars_derive | 0.8.22 | MIT | https://github.com/GREsau/schemars |  |
| scopeguard | 1.2.0 | MIT OR Apache-2.0 | https://github.com/bluss/scopeguard |  |
| seahash | 4.1.0 | MIT | https://gitlab.redox-os.org/redox-os/seahash |  |
| security-framework | 3.5.1 | MIT OR Apache-2.0 | https://github.com/kornelski/rust-security-framework |  |
| security-framework-sys | 2.15.0 | MIT OR Apache-2.0 | https://github.com/kornelski/rust-security-framework |  |
| selectors | 0.24.0 | MPL-2.0 | https://github.com/servo/servo |  |
| semver | 1.0.27 | MIT OR Apache-2.0 | https://github.com/dtolnay/semver |  |
| serde | 1.0.228 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |  |
| serde-untagged | 0.1.9 | MIT OR Apache-2.0 | https://github.com/dtolnay/serde-untagged |  |
| serde_core | 1.0.228 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |  |
| serde_derive | 1.0.228 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |  |
| serde_derive_internals | 0.29.1 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |  |
| serde_json | 1.0.146 | MIT OR Apache-2.0 | https://github.com/serde-rs/json |  |
| serde_repr | 0.1.20 | MIT OR Apache-2.0 | https://github.com/dtolnay/serde-repr |  |
| serde_spanned | 0.6.9, 1.0.4 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| serde_urlencoded | 0.7.1 | MIT OR Apache-2.0 | https://github.com/nox/serde_urlencoded |  |
| serde_with | 3.16.1 | MIT OR Apache-2.0 | https://github.com/jonasbb/serde_with/ |  |
| serde_with_macros | 3.16.1 | MIT OR Apache-2.0 | https://github.com/jonasbb/serde_with/ |  |
| serialize-to-javascript | 0.1.2 | MIT OR Apache-2.0 | https://github.com/chippers/serialize-to-javascript |  |
| serialize-to-javascript-impl | 0.1.2 | MIT OR Apache-2.0 | https://github.com/chippers/serialize-to-javascript |  |
| servo_arc | 0.2.0 | MIT OR Apache-2.0 | https://github.com/servo/servo |  |
| sha2 | 0.10.9 | MIT OR Apache-2.0 | https://github.com/RustCrypto/hashes |  |
| shared_child | 1.1.1 | MIT | https://github.com/oconnor663/shared_child.rs |  |
| sherpa-onnx | 1.13.3 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |  |
| sherpa-onnx-sys | 1.13.3 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |  |
| shlex | 1.3.0 | MIT OR Apache-2.0 | https://github.com/comex/rust-shlex | build-time only |
| sigchld | 0.2.4 | MIT | https://github.com/oconnor663/sigchld.rs |  |
| signal-hook | 0.3.18 | Apache-2.0 OR MIT | https://github.com/vorner/signal-hook |  |
| signal-hook-registry | 1.4.7 | MIT OR Apache-2.0 | https://github.com/vorner/signal-hook |  |
| simd-adler32 | 0.3.8 | MIT | https://github.com/mcountryman/simd-adler32 |  |
| simdutf8 | 0.1.5 | MIT OR Apache-2.0 | https://github.com/rusticstuff/simdutf8 |  |
| siphasher | 0.3.11, 1.0.1 | MIT OR Apache-2.0 | https://github.com/jedisct1/rust-siphash |  |
| slab | 0.4.11 | MIT | https://github.com/tokio-rs/slab |  |
| smallvec | 1.15.1 | MIT OR Apache-2.0 | https://github.com/servo/rust-smallvec |  |
| socket2 | 0.6.1 | MIT OR Apache-2.0 | https://github.com/rust-lang/socket2 |  |
| softbuffer | 0.4.8 | MIT OR Apache-2.0 | https://github.com/rust-windowing/softbuffer |  |
| soup3 | 0.5.0 | MIT | https://gitlab.gnome.org/World/Rust/soup3-rs |  |
| soup3-sys | 0.5.0 | MIT | https://gitlab.gnome.org/World/Rust/soup3-rs |  |
| stable_deref_trait | 1.2.1 | MIT OR Apache-2.0 | https://github.com/storyyeller/stable_deref_trait |  |
| string_cache | 0.8.9 | MIT OR Apache-2.0 | https://github.com/servo/string-cache |  |
| string_cache_codegen | 0.5.4 | MIT OR Apache-2.0 | https://github.com/servo/string-cache | build-time only |
| strsim | 0.11.1 | MIT | https://github.com/rapidfuzz/strsim-rs |  |
| subtle | 2.6.1 | BSD-3-Clause | https://github.com/dalek-cryptography/subtle |  |
| swift-rs | 1.0.7 | MIT OR Apache-2.0 | https://github.com/Brendonovich/swift-rs |  |
| syn | 1.0.109, 2.0.111 | MIT OR Apache-2.0 | https://github.com/dtolnay/syn |  |
| sync_wrapper | 1.0.2 | Apache-2.0 | https://github.com/Actyx/sync_wrapper |  |
| synstructure | 0.13.2 | MIT | https://github.com/mystor/synstructure |  |
| system-deps | 6.2.2 | MIT OR Apache-2.0 | https://github.com/gdesmott/system-deps | build-time only |
| tao | 0.34.5 | Apache-2.0 | https://github.com/tauri-apps/tao |  |
| tao-macros | 0.1.3 | MIT OR Apache-2.0 | https://github.com/tauri-apps/tao |  |
| tap | 1.0.1 | MIT | https://github.com/myrrlyn/tap |  |
| tar | 0.4.44 | MIT OR Apache-2.0 | https://github.com/alexcrichton/tar-rs |  |
| target-lexicon | 0.12.16 | Apache-2.0 WITH LLVM-exception | https://github.com/bytecodealliance/target-lexicon | build-time only |
| tauri | 2.10.2 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |  |
| tauri-build | 2.5.5 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri | build-time only |
| tauri-codegen | 2.5.4 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |  |
| tauri-macros | 2.5.4 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |  |
| tauri-plugin | 2.5.2 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri | build-time only |
| tauri-plugin-clipboard-manager | 2.3.2 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-dialog | 2.5.0 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-drag | 2.1.0 | Apache-2.0 OR MIT |  |  |
| tauri-plugin-fs | 2.4.5 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-log | 2.7.1 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-opener | 2.5.3 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-process | 2.3.1 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-shell | 2.3.3 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-single-instance | 2.4.2 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-updater | 2.10.0 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-plugin-window-state | 2.4.1 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |  |
| tauri-runtime | 2.10.0 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |  |
| tauri-runtime-wry | 2.10.0 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |  |
| tauri-utils | 2.8.2 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |  |
| tauri-winres | 0.3.5 | MIT | https://github.com/tauri-apps/winres | build-time only |
| tempfile | 3.24.0 | MIT OR Apache-2.0 | https://github.com/Stebalien/tempfile |  |
| tendril | 0.4.3 | MIT OR Apache-2.0 | https://github.com/servo/tendril |  |
| thiserror | 1.0.69, 2.0.17 | MIT OR Apache-2.0 | https://github.com/dtolnay/thiserror |  |
| thiserror-impl | 1.0.69, 2.0.17 | MIT OR Apache-2.0 | https://github.com/dtolnay/thiserror |  |
| tiff | 0.10.3 | MIT | https://github.com/image-rs/image-tiff |  |
| time | 0.3.44 | MIT OR Apache-2.0 | https://github.com/time-rs/time |  |
| time-core | 0.1.6 | MIT OR Apache-2.0 | https://github.com/time-rs/time |  |
| time-macros | 0.2.24 | MIT OR Apache-2.0 | https://github.com/time-rs/time |  |
| tinystr | 0.8.2 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| tinyvec | 1.10.0 | Zlib OR Apache-2.0 OR MIT | https://github.com/Lokathor/tinyvec |  |
| tinyvec_macros | 0.1.1 | MIT OR Apache-2.0 OR Zlib | https://github.com/Soveu/tinyvec_macros |  |
| tokio | 1.48.0 | MIT | https://github.com/tokio-rs/tokio |  |
| tokio-rustls | 0.26.4 | MIT OR Apache-2.0 | https://github.com/rustls/tokio-rustls |  |
| tokio-util | 0.7.17 | MIT | https://github.com/tokio-rs/tokio |  |
| toml | 0.8.2, 0.9.10+spec-1.1.0 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| toml_datetime | 0.6.3, 0.7.5+spec-1.1.0 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| toml_edit | 0.19.15, 0.20.2, 0.23.10+spec-1.0.0 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| toml_parser | 1.0.6+spec-1.1.0 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| toml_writer | 1.0.6+spec-1.1.0 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| tower | 0.5.2 | MIT | https://github.com/tower-rs/tower |  |
| tower-http | 0.6.8 | MIT | https://github.com/tower-rs/tower-http |  |
| tower-layer | 0.3.3 | MIT | https://github.com/tower-rs/tower |  |
| tower-service | 0.3.3 | MIT | https://github.com/tower-rs/tower |  |
| tracing | 0.1.44 | MIT | https://github.com/tokio-rs/tracing |  |
| tracing-attributes | 0.1.31 | MIT | https://github.com/tokio-rs/tracing |  |
| tracing-core | 0.1.36 | MIT | https://github.com/tokio-rs/tracing |  |
| tray-icon | 0.21.2 | MIT OR Apache-2.0 | https://github.com/tauri-apps/tray-icon |  |
| tree_magic_mini | 3.2.2 | MIT | https://github.com/mbrubeck/tree_magic/ |  |
| try-lock | 0.2.5 | MIT | https://github.com/seanmonstar/try-lock |  |
| typeid | 1.0.3 | MIT OR Apache-2.0 | https://github.com/dtolnay/typeid |  |
| typenum | 1.19.0 | MIT OR Apache-2.0 | https://github.com/paholg/typenum |  |
| uds_windows | 1.1.0 | MIT | https://github.com/haraldh/rust_uds_windows |  |
| unic-char-property | 0.9.0 | MIT OR Apache-2.0 | https://github.com/open-i18n/rust-unic/ |  |
| unic-char-range | 0.9.0 | MIT OR Apache-2.0 | https://github.com/open-i18n/rust-unic/ |  |
| unic-common | 0.9.0 | MIT OR Apache-2.0 | https://github.com/open-i18n/rust-unic/ |  |
| unic-ucd-ident | 0.9.0 | MIT OR Apache-2.0 | https://github.com/open-i18n/rust-unic/ |  |
| unic-ucd-version | 0.9.0 | MIT OR Apache-2.0 | https://github.com/open-i18n/rust-unic/ |  |
| unicode-ident | 1.0.22 | (MIT OR Apache-2.0) AND Unicode-3.0 | https://github.com/dtolnay/unicode-ident |  |
| unicode-segmentation | 1.12.0 | MIT OR Apache-2.0 | https://github.com/unicode-rs/unicode-segmentation |  |
| untrusted | 0.9.0 | ISC | https://github.com/briansmith/untrusted |  |
| ureq | 2.12.1 | MIT OR Apache-2.0 | https://github.com/algesten/ureq | build-time only |
| url | 2.5.7 | MIT OR Apache-2.0 | https://github.com/servo/rust-url |  |
| urlpattern | 0.3.0 | MIT | https://github.com/denoland/rust-urlpattern |  |
| utf-8 | 0.7.6 | MIT OR Apache-2.0 | https://github.com/SimonSapin/rust-utf8 |  |
| utf8-width | 0.1.8 | MIT | https://github.com/magiclen/utf8-width |  |
| utf8_iter | 1.0.4 | Apache-2.0 OR MIT | https://github.com/hsivonen/utf8_iter |  |
| uuid | 1.19.0 | Apache-2.0 OR MIT | https://github.com/uuid-rs/uuid |  |
| value-bag | 1.12.0 | Apache-2.0 OR MIT | https://github.com/sval-rs/value-bag |  |
| version-compare | 0.2.1 | MIT | https://gitlab.com/timvisee/version-compare | build-time only |
| version_check | 0.9.5 | MIT OR Apache-2.0 | https://github.com/SergioBenitez/version_check | build-time only |
| vswhom | 0.1.0 | MIT | https://github.com/nabijaczleweli/vswhom.rs | build-time only |
| vswhom-sys | 0.1.3 | MIT | https://github.com/nabijaczleweli/vswhom-sys.rs | build-time only |
| walkdir | 2.5.0 | Unlicense OR MIT | https://github.com/BurntSushi/walkdir |  |
| want | 0.3.1 | MIT | https://github.com/seanmonstar/want |  |
| wasi | 0.11.1+wasi-snapshot-preview1, 0.9.0+wasi-snapshot-preview1 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/bytecodealliance/wasi |  |
| wasip2 | 1.0.1+wasi-0.2.4 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/bytecodealliance/wasi-rs |  |
| wasm-bindgen | 0.2.108 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen |  |
| wasm-bindgen-futures | 0.4.58 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/futures |  |
| wasm-bindgen-macro | 0.2.108 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/macro |  |
| wasm-bindgen-macro-support | 0.2.108 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/macro-support |  |
| wasm-bindgen-shared | 0.2.108 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/shared |  |
| wasm-streams | 0.4.2, 0.5.0 | MIT OR Apache-2.0 | https://github.com/MattiasBuelens/wasm-streams/ |  |
| wayland-backend | 0.3.12 | MIT | https://github.com/smithay/wayland-rs |  |
| wayland-client | 0.31.12 | MIT | https://github.com/smithay/wayland-rs |  |
| wayland-protocols | 0.32.10 | MIT | https://github.com/smithay/wayland-rs |  |
| wayland-protocols-wlr | 0.3.10 | MIT | https://github.com/smithay/wayland-rs |  |
| wayland-scanner | 0.31.8 | MIT | https://github.com/smithay/wayland-rs |  |
| wayland-sys | 0.31.8 | MIT | https://github.com/smithay/wayland-rs |  |
| web-sys | 0.3.85 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/web-sys |  |
| web-time | 1.1.0 | MIT OR Apache-2.0 | https://github.com/daxpedda/web-time |  |
| webkit2gtk | 2.0.2 | MIT | https://github.com/tauri-apps/webkit2gtk-rs |  |
| webkit2gtk-sys | 2.0.2 | MIT | https://github.com/tauri-apps/webkit2gtk-rs |  |
| webpki-root-certs | 1.0.6 | CDLA-Permissive-2.0 | https://github.com/rustls/webpki-roots |  |
| webpki-roots | 0.26.11, 1.0.7 | CDLA-Permissive-2.0 | https://github.com/rustls/webpki-roots |  |
| webview2-com | 0.38.0 | MIT | https://github.com/wravery/webview2-rs |  |
| webview2-com-macros | 0.8.0 | MIT | https://github.com/wravery/webview2-rs |  |
| webview2-com-sys | 0.38.0 | MIT | https://github.com/wravery/webview2-rs |  |
| weezl | 0.1.12 | MIT OR Apache-2.0 | https://github.com/image-rs/weezl |  |
| which | 4.4.2 | MIT | https://github.com/harryfei/which-rs | build-time only |
| whisper-rs | 0.12.0 | Unlicense | https://github.com/tazz4843/whisper-rs |  |
| whisper-rs-sys | 0.10.0 | Unlicense | https://github.com/tazz4843/whisper-rs |  |
| winapi | 0.3.9 | MIT OR Apache-2.0 | https://github.com/retep998/winapi-rs |  |
| winapi-i686-pc-windows-gnu | 0.4.0 | MIT OR Apache-2.0 | https://github.com/retep998/winapi-rs |  |
| winapi-util | 0.1.11 | Unlicense OR MIT | https://github.com/BurntSushi/winapi-util |  |
| winapi-x86_64-pc-windows-gnu | 0.4.0 | MIT OR Apache-2.0 | https://github.com/retep998/winapi-rs |  |
| window-vibrancy | 0.6.0 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri-plugin-vibrancy |  |
| windows | 0.52.0, 0.54.0, 0.61.3 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-collections | 0.2.0 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-core | 0.52.0, 0.54.0, 0.58.0, 0.61.2, 0.62.2 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-future | 0.2.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-implement | 0.52.0, 0.58.0, 0.60.2 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-interface | 0.52.0, 0.58.0, 0.59.3 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-link | 0.1.3, 0.2.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-numerics | 0.2.0 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-result | 0.1.2, 0.2.0, 0.3.4, 0.4.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-strings | 0.1.0, 0.4.2, 0.5.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-sys | 0.45.0, 0.52.0, 0.59.0, 0.60.2, 0.61.2 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-targets | 0.42.2, 0.52.6, 0.53.5 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-threading | 0.1.0 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-version | 0.1.7 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_aarch64_gnullvm | 0.42.2, 0.52.6, 0.53.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_aarch64_msvc | 0.42.2, 0.52.6, 0.53.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_i686_gnu | 0.42.2, 0.52.6, 0.53.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_i686_gnullvm | 0.52.6, 0.53.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_i686_msvc | 0.42.2, 0.52.6, 0.53.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_x86_64_gnu | 0.42.2, 0.52.6, 0.53.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_x86_64_gnullvm | 0.42.2, 0.52.6, 0.53.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_x86_64_msvc | 0.42.2, 0.52.6, 0.53.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| winnow | 0.5.40, 0.7.14 | MIT | https://github.com/winnow-rs/winnow |  |
| winreg | 0.55.0 | MIT | https://github.com/gentoo90/winreg-rs | build-time only |
| wit-bindgen | 0.46.0 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/bytecodealliance/wit-bindgen |  |
| wl-clipboard-rs | 0.9.3 | MIT OR Apache-2.0 | https://github.com/YaLTeR/wl-clipboard-rs |  |
| writeable | 0.6.2 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| wry | 0.54.1 | Apache-2.0 OR MIT | https://github.com/tauri-apps/wry |  |
| wyz | 0.5.1 | MIT | https://github.com/myrrlyn/wyz |  |
| x11 | 2.21.0 | MIT | https://github.com/AltF02/x11-rs |  |
| x11-dl | 2.21.0 | MIT | https://github.com/AltF02/x11-rs |  |
| x11rb | 0.13.2 | MIT OR Apache-2.0 | https://github.com/psychon/x11rb |  |
| x11rb-protocol | 0.13.2 | MIT OR Apache-2.0 | https://github.com/psychon/x11rb |  |
| xattr | 1.6.1 | MIT OR Apache-2.0 | https://github.com/Stebalien/xattr |  |
| yoke | 0.8.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| yoke-derive | 0.8.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zbus | 5.13.2 | MIT | https://github.com/z-galaxy/zbus/ |  |
| zbus_macros | 5.13.2 | MIT | https://github.com/z-galaxy/zbus/ |  |
| zbus_names | 4.3.1 | MIT | https://github.com/z-galaxy/zbus/ |  |
| zerocopy | 0.8.31 | BSD-2-Clause OR Apache-2.0 OR MIT | https://github.com/google/zerocopy |  |
| zerocopy-derive | 0.8.31 | BSD-2-Clause OR Apache-2.0 OR MIT | https://github.com/google/zerocopy |  |
| zerofrom | 0.1.6 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zerofrom-derive | 0.1.6 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zeroize | 1.8.2 | Apache-2.0 OR MIT | https://github.com/RustCrypto/utils |  |
| zerotrie | 0.2.3 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zerovec | 0.11.5 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zerovec-derive | 0.11.2 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zip | 4.6.1 | MIT | https://github.com/zip-rs/zip2 |  |
| zune-core | 0.4.12 | MIT OR Apache-2.0 OR Zlib |  |  |
| zune-jpeg | 0.4.21 | MIT OR Apache-2.0 OR Zlib | https://github.com/etemesi254/zune-image/tree/dev/crates/zune-jpeg |  |
| zvariant | 5.9.2 | MIT | https://github.com/z-galaxy/zbus/ |  |
| zvariant_derive | 5.9.2 | MIT | https://github.com/z-galaxy/zbus/ |  |
| zvariant_utils | 3.3.0 | MIT | https://github.com/z-galaxy/zbus/ |  |
<!-- END GENERATED: rust -->
