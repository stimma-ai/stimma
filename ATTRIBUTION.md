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
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | On-device speech recognition runtime | Apache-2.0 |
| [ONNX Runtime](https://onnxruntime.ai/) | ML inference engine (Python package and via sherpa-onnx) | MIT |
| [PDFium](https://pdfium.googlesource.com/pdfium/) via [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | PDF rendering; bundles FreeType, libjpeg-turbo, libpng, libtiff, OpenJPEG, ICU, LCMS, and other permissively licensed libraries — see pypdfium2's bundled `LICENSES` file | BSD-3-Clause / Apache-2.0 |

Stimma does **not** bundle FFmpeg. Video features use an FFmpeg installation
already present on your system, and the build pipeline actively verifies
that no FFmpeg or restricted codec libraries ship in the app.

## Android native shell

The Android shell also bundles these Apache-2.0 libraries and their supporting
AndroidX/Kotlin modules. Versions are declared in `mobile/android/app/build.gradle.kts`.

| Project | Use | License |
|---|---|---|
| [AndroidX](https://android.googlesource.com/platform/frameworks/support/) | Activity, lifecycle, WebKit, Custom Tabs, core, and supporting Android components | Apache-2.0 |
| [Kotlin](https://github.com/JetBrains/kotlin), [kotlinx.coroutines](https://github.com/Kotlin/kotlinx.coroutines) | Kotlin runtime and native asynchronous operations | Apache-2.0 |
| [OkHttp](https://github.com/square/okhttp), [Okio](https://github.com/square/okio) | Native HTTP and byte streams | Apache-2.0 |
| [JetBrains annotations](https://github.com/JetBrains/java-annotations), [JSpecify](https://github.com/jspecify/jspecify) | Runtime dependency annotations | Apache-2.0 |

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
| [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) (int8 ONNX via [sherpa-onnx](https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8)) | NVIDIA NeMo | Voice input | CC-BY-4.0 |
| [SAM 3](https://github.com/facebookresearch/sam3) (ONNX export via [wkentaro/sam3-onnx-models](https://huggingface.co/wkentaro/sam3-onnx-models)) | Meta AI | Segmentation / masking | SAM License (Meta; commercial use permitted, acceptable-use restrictions apply — full text distributed with the model) |
| [BEN2 Base](https://huggingface.co/PramaLLC/BEN2) (official ONNX artifact) | Prama LLC | Subject and background selection | MIT |
| [SkyWater-Seg](https://huggingface.co/Realcat/skywater_seg) (SegFormer MiT-B2 ONNX) | Vincent Qin | Sky selection | MIT |
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
136 packages (direct and transitive; the entire environment is bundled with the app).

| Package | Version | License | Source |
|---|---|---|---|
| aiohttp | 3.9.1 | Apache-2.0 | https://github.com/aio-libs/aiohttp |
| aiosignal | 1.4.0 | Apache-2.0 | https://github.com/aio-libs/aiosignal |
| aiosqlite | 0.19.0 | MIT | https://aiosqlite.omnilib.dev |
| alembic | 1.17.2 | MIT | https://alembic.sqlalchemy.org |
| annotated-doc | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.7.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.14.2 | MIT | https://github.com/agronholm/anyio |
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
| fastapi | 0.141.1 | MIT | https://github.com/fastapi/fastapi |
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
| httptools | 0.8.0 | MIT | https://github.com/MagicStack/httptools |
| httpx | 0.28.1 | BSD | https://github.com/encode/httpx |
| httpx-sse | 0.4.3 | MIT | https://github.com/florimondmanca/httpx-sse |
| huggingface-hub | 1.4.1 | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| humanfriendly | 10.0 | MIT | https://humanfriendly.readthedocs.io |
| idna | 3.11 | BSD-3-Clause | https://github.com/kjd/idna |
| imageio | 2.37.2 | BSD-2-Clause | https://github.com/imageio/imageio |
| imgviz | 1.8.0 | MIT | https://github.com/wkentaro/imgviz |
| jeepney | 0.9.0 | MIT | https://gitlab.com/takluyver/jeepney |
| jsonschema | 4.26.0 | MIT | https://github.com/python-jsonschema/jsonschema |
| jsonschema-specifications | 2025.9.1 | MIT | https://github.com/python-jsonschema/jsonschema-specifications |
| justext | 3.0.2 | BSD | https://github.com/miso-belica/jusText |
| lazy-loader | 0.4 | BSD | https://github.com/scientific-python/lazy_loader |
| loguru | 0.7.3 | MIT | https://github.com/Delgan/loguru |
| lxml | 6.0.2 | BSD-3-Clause | https://lxml.de/ |
| lxml-html-clean | 0.4.4 | BSD-3-Clause | https://github.com/fedora-python/lxml_html_clean/ |
| mako | 1.3.10 | MIT | https://www.makotemplates.org/ |
| markdown | 3.10.1 | BSD-3-Clause | https://Python-Markdown.github.io/ |
| markdown-it-py | 4.0.0 | MIT | https://github.com/executablebooks/markdown-it-py |
| markupsafe | 3.0.3 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| mcp | 1.29.1 | MIT | https://modelcontextprotocol.io |
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
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pydantic | 2.13.5 | MIT | https://github.com/pydantic/pydantic |
| pydantic-core | 2.46.5 | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | 2.15.0 | MIT | https://github.com/pydantic/pydantic-settings |
| pydyf | 0.12.1 | BSD | https://www.courtbouillon.org/pydyf |
| pygments | 2.19.2 | BSD | https://pygments.org |
| pyjwt | 2.13.0 | MIT | https://github.com/jpadilla/pyjwt |
| pypdfium2 | 5.6.0 | BSD-3-Clause AND Apache-2.0 (bundles PDFium and its third-party libraries) | https://github.com/pypdfium2-team/pypdfium2 |
| pyphen | 0.17.2 | GPL-2.0+ OR LGPL-2.1+ OR MPL-1.1 (used under MPL-1.1) | https://www.courtbouillon.org/pyphen |
| pyreadline3 | 3.5.4 | BSD-3-Clause | https://github.com/pyreadline3/pyreadline3 |
| pysocks | 1.7.1 | BSD-3-Clause | https://github.com/Anorov/PySocks |
| python-dateutil | 2.9.0.post0 | BSD | https://github.com/dateutil/dateutil |
| python-dotenv | 1.2.1 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| python-frontmatter | 1.1.0 | MIT | https://github.com/eyeseast/python-frontmatter |
| python-multipart | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| pytz | 2026.1.post1 | MIT | http://pythonhosted.org/pytz |
| pywin32 | 312 | PSF-2.0 AND BSD-3-Clause AND (PSF-2.0 OR BSD-3-Clause) AND Python-2.0.1 AND MIT AND LGPL-2.1-or-later | https://github.com/mhammond/pywin32 |
| pyyaml | 6.0.1 | MIT | https://pyyaml.org/ |
| referencing | 0.37.0 | MIT | https://github.com/python-jsonschema/referencing |
| regex | 2025.11.3 | Apache-2.0 AND CNRI-Python | https://github.com/mrabarnett/mrab-regex |
| requests | 2.32.5 | Apache-2.0 | https://requests.readthedocs.io |
| rich | 14.3.2 | MIT | https://github.com/Textualize/rich |
| rpds-py | 2026.6.3 | MIT | https://github.com/crate-py/rpds |
| ruamel-yaml | 0.19.1 | MIT | https://sourceforge.net/p/ruamel-yaml/code/ci/default/tree/ |
| scikit-image | 0.23.2 | BSD | https://scikit-image.org |
| scipy | 1.16.3 | BSD | https://scipy.org/ |
| secretstorage | 3.5.0 | BSD-3-Clause | https://github.com/mitya57/secretstorage |
| shellingham | 1.5.4 | ISC | https://github.com/sarugaku/shellingham |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| soupsieve | 2.8.1 | MIT | https://github.com/facelessuser/soupsieve |
| sqlalchemy | 2.0.23 | MIT | https://www.sqlalchemy.org |
| sse-starlette | 1.8.2 | BSD | https://github.com/sysid/sse-starlette |
| starlette | 1.6.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
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
| typing-inspection | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| tzdata | 2025.3 | Apache-2.0 | https://github.com/python/tzdata |
| tzlocal | 5.3.1 | MIT | https://github.com/regebro/tzlocal |
| urllib3 | 2.6.2 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| uvicorn | 0.50.1 | BSD-3-Clause | https://uvicorn.dev/ |
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
117 packages (production dependency closure bundled into the UI).

| Package | Version | License | Source |
|---|---|---|---|
| @babel/helper-string-parser | 7.27.1 | MIT | https://github.com/babel/babel |
| @babel/helper-validator-identifier | 7.28.5 | MIT | https://github.com/babel/babel |
| @babel/parser | 7.28.5 | MIT | https://github.com/babel/babel |
| @babel/types | 7.28.5 | MIT | https://github.com/babel/babel |
| @codemirror/autocomplete | 6.20.2 | MIT | https://code.haverbeke.berlin/codemirror/autocomplete |
| @codemirror/commands | 6.10.3 | MIT | https://github.com/codemirror/commands |
| @codemirror/lang-css | 6.3.1 | MIT | https://github.com/codemirror/lang-css |
| @codemirror/lang-html | 6.4.12 | MIT | https://code.haverbeke.berlin/codemirror/lang-html |
| @codemirror/lang-javascript | 6.2.5 | MIT | https://github.com/codemirror/lang-javascript |
| @codemirror/lang-json | 6.0.2 | MIT | https://github.com/codemirror/lang-json |
| @codemirror/lang-markdown | 6.5.2 | MIT | https://code.haverbeke.berlin/codemirror/lang-markdown |
| @codemirror/lang-python | 6.2.1 | MIT | https://github.com/codemirror/lang-python |
| @codemirror/lang-sql | 6.10.0 | MIT | https://github.com/codemirror/lang-sql |
| @codemirror/language | 6.12.3 | MIT | https://github.com/codemirror/language |
| @codemirror/lint | 6.9.7 | MIT | https://code.haverbeke.berlin/codemirror/lint |
| @codemirror/search | 6.7.0 | MIT | https://code.haverbeke.berlin/codemirror/search |
| @codemirror/state | 6.6.0 | MIT | https://github.com/codemirror/state |
| @codemirror/view | 6.43.0 | MIT | https://code.haverbeke.berlin/codemirror/view |
| @dagrejs/dagre | 3.0.0 | MIT | https://github.com/dagrejs/dagre |
| @dagrejs/graphlib | 4.0.1 | MIT | https://github.com/dagrejs/graphlib |
| @electron-internal/extract-zip | 1.0.5 | BSD-2-Clause | https://github.com/electron/extract-zip |
| @electron/get | 5.1.0 | MIT | https://github.com/electron/get |
| @heroicons/vue | 2.2.0 | MIT | https://github.com/tailwindlabs/heroicons |
| @jridgewell/sourcemap-codec | 1.5.5 | MIT | https://github.com/jridgewell/sourcemaps |
| @lezer/common | 1.5.1 | MIT | https://github.com/lezer-parser/common |
| @lezer/css | 1.3.6 | MIT | https://code.haverbeke.berlin/lezer/css |
| @lezer/highlight | 1.2.3 | MIT | https://github.com/lezer-parser/highlight |
| @lezer/html | 1.3.13 | MIT | https://github.com/lezer-parser/html |
| @lezer/javascript | 1.5.4 | MIT | https://github.com/lezer-parser/javascript |
| @lezer/json | 1.0.3 | MIT | https://github.com/lezer-parser/json |
| @lezer/lr | 1.4.8 | MIT | https://github.com/lezer-parser/lr |
| @lezer/markdown | 1.7.2 | MIT | https://code.haverbeke.berlin/lezer/markdown |
| @lezer/python | 1.1.18 | MIT | https://github.com/lezer-parser/python |
| @marijn/find-cluster-break | 1.0.2 | MIT | https://github.com/marijnh/find-cluster-break |
| @replit/codemirror-vim | 6.3.0 | MIT | https://github.com/replit/codemirror-vim |
| @tailwindcss/typography | 0.5.19 | MIT | https://github.com/tailwindlabs/tailwindcss-typography |
| @types/node | 24.13.3 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
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
| agent-base | 6.0.2 | MIT | https://github.com/TooTallNate/node-agent-base |
| argparse | 2.0.1 | Python-2.0 | https://github.com/nodeca/argparse |
| asynckit | 0.4.0 | MIT | https://github.com/alexindigo/asynckit |
| axios | 1.18.0 | MIT | https://github.com/axios/axios |
| builder-util-runtime | 9.7.0 | MIT | https://github.com/electron-userland/electron-builder |
| call-bind-apply-helpers | 1.0.2 | MIT | https://github.com/ljharb/call-bind-apply-helpers |
| combined-stream | 1.0.8 | MIT | https://github.com/felixge/node-combined-stream |
| crelt | 1.0.6 | MIT | https://github.com/marijnh/crelt |
| cssesc | 3.0.0 | MIT | https://github.com/mathiasbynens/cssesc |
| csstype | 3.2.1 | MIT | https://github.com/frenic/csstype |
| debug | 4.4.3 | MIT | https://github.com/debug-js/debug |
| delayed-stream | 1.0.0 | MIT | https://github.com/felixge/node-delayed-stream |
| dompurify | 3.4.11 | (MPL-2.0 OR Apache-2.0) | https://github.com/cure53/DOMPurify |
| dunder-proto | 1.0.1 | MIT | https://github.com/es-shims/dunder-proto |
| electron | 44.0.0 | MIT | https://github.com/electron/electron |
| electron-updater | 6.8.9 | MIT | https://github.com/electron-userland/electron-builder |
| entities | 4.5.0 | BSD-2-Clause | https://github.com/fb55/entities |
| env-paths | 3.0.0 | MIT | https://github.com/sindresorhus/env-paths |
| es-define-property | 1.0.1 | MIT | https://github.com/ljharb/es-define-property |
| es-errors | 1.3.0 | MIT | https://github.com/ljharb/es-errors |
| es-object-atoms | 1.1.2 | MIT | https://github.com/ljharb/es-object-atoms |
| es-set-tostringtag | 2.1.0 | MIT | https://github.com/es-shims/es-set-tostringtag |
| estree-walker | 2.0.2 | MIT | https://github.com/Rich-Harris/estree-walker |
| fflate | 0.8.3 | MIT | https://github.com/101arrowz/fflate |
| follow-redirects | 1.16.0 | MIT | https://github.com/follow-redirects/follow-redirects |
| form-data | 4.0.6 | MIT | https://github.com/form-data/form-data |
| fs-extra | 10.1.0 | MIT | https://github.com/jprichardson/node-fs-extra |
| function-bind | 1.1.2 | MIT | https://github.com/Raynos/function-bind |
| get-intrinsic | 1.3.0 | MIT | https://github.com/ljharb/get-intrinsic |
| get-proto | 1.0.1 | MIT | https://github.com/ljharb/get-proto |
| gopd | 1.2.0 | MIT | https://github.com/ljharb/gopd |
| graceful-fs | 4.2.11 | ISC | https://github.com/isaacs/node-graceful-fs |
| has-symbols | 1.1.0 | MIT | https://github.com/inspect-js/has-symbols |
| has-tostringtag | 1.0.2 | MIT | https://github.com/inspect-js/has-tostringtag |
| hasown | 2.0.4 | MIT | https://github.com/inspect-js/hasOwn |
| https-proxy-agent | 5.0.1 | MIT | https://github.com/TooTallNate/node-https-proxy-agent |
| js-yaml | 4.3.2 | MIT | https://github.com/nodeca/js-yaml |
| jsonfile | 6.2.1 | MIT | https://github.com/git@github.com:jprichardson/node-jsonfile |
| lazy-val | 1.0.5 | MIT | https://github.com/develar/lazy-val |
| lodash.escaperegexp | 4.1.2 | MIT | https://github.com/lodash/lodash |
| lodash.isequal | 4.5.0 | MIT | https://github.com/lodash/lodash |
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
| progress | 2.0.3 | MIT | https://github.com/visionmedia/node-progress |
| proxy-from-env | 2.1.0 | MIT | https://github.com/Rob--W/proxy-from-env |
| sax | 1.6.1 | BlueOak-1.0.0 | https://github.com/isaacs/sax-js |
| semver | 7.8.5 | ISC | https://github.com/npm/node-semver |
| source-map-js | 1.2.1 | BSD-3-Clause | https://github.com/7rulnik/source-map-js |
| style-mod | 4.1.3 | MIT | https://github.com/marijnh/style-mod |
| sumchecker | 3.0.1 | Apache-2.0 | https://github.com/malept/sumchecker |
| tiny-typed-emitter | 2.1.0 | MIT | https://github.com/binier/tiny-typed-emitter |
| undici-types | 7.18.2 | MIT | https://github.com/nodejs/undici |
| universalify | 2.0.1 | MIT | https://github.com/RyanZim/universalify |
| util-deprecate | 1.0.2 | MIT | https://github.com/TooTallNate/util-deprecate |
| vue | 3.5.24 | MIT | https://github.com/vuejs/core |
| vue-observe-visibility | 2.0.0-alpha.1 | MIT | https://github.com/Akryum/vue-observe-visibility |
| vue-resize | 2.0.0-alpha.1 | MIT | https://github.com/Akryum/vue-resize |
| vue-router | 4.6.3 | MIT | https://github.com/vuejs/router |
| vue-virtual-scroller | 2.0.0-beta.8 | MIT | https://github.com/Akryum/vue-virtual-scroller |
| w3c-keyname | 2.2.8 | MIT | https://github.com/marijnh/w3c-keyname |
<!-- END GENERATED: npm -->

## Rust crates

<!-- BEGIN GENERATED: rust -->
244 crates (208 compiled into shipped binaries; the rest are marked build-time only).

| Crate | Version(s) | License | Source | Notes |
|---|---|---|---|---|
| adler2 | 2.0.1 | 0BSD OR MIT OR Apache-2.0 | https://github.com/oyvindln/adler2 | build-time only |
| ahash | 0.8.12 | MIT OR Apache-2.0 | https://github.com/tkaitchuck/ahash |  |
| aho-corasick | 1.1.5 | Unlicense OR MIT | https://github.com/BurntSushi/aho-corasick |  |
| alsa | 0.9.1 | Apache-2.0 OR MIT | https://github.com/diwic/alsa-rs |  |
| alsa-sys | 0.3.1 | MIT | https://github.com/diwic/alsa-sys |  |
| anstream | 1.0.0 | MIT OR Apache-2.0 | https://github.com/rust-cli/anstyle |  |
| anstyle | 1.0.14 | MIT OR Apache-2.0 | https://github.com/rust-cli/anstyle |  |
| anstyle-parse | 1.0.0 | MIT OR Apache-2.0 | https://github.com/rust-cli/anstyle |  |
| anstyle-query | 1.1.5 | MIT OR Apache-2.0 | https://github.com/rust-cli/anstyle |  |
| anstyle-wincon | 3.0.11 | MIT OR Apache-2.0 | https://github.com/rust-cli/anstyle |  |
| atomic-waker | 1.1.2 | Apache-2.0 OR MIT | https://github.com/smol-rs/atomic-waker |  |
| autocfg | 1.5.1 | Apache-2.0 OR MIT | https://github.com/cuviper/autocfg | build-time only |
| base64 | 0.22.1 | MIT OR Apache-2.0 | https://github.com/marshallpierce/rust-base64 |  |
| bindgen | 0.72.1 | BSD-3-Clause | https://github.com/rust-lang/rust-bindgen | build-time only |
| bitflags | 1.3.2, 2.13.1 | MIT OR Apache-2.0 | https://github.com/bitflags/bitflags |  |
| bumpalo | 3.20.3 | MIT OR Apache-2.0 | https://github.com/fitzgen/bumpalo |  |
| bytes | 1.12.1 | MIT | https://github.com/tokio-rs/bytes |  |
| bzip2 | 0.4.4 | MIT OR Apache-2.0 | https://github.com/alexcrichton/bzip2-rs | build-time only |
| bzip2-sys | 0.1.13+1.0.8 | MIT OR Apache-2.0 | https://github.com/alexcrichton/bzip2-rs | build-time only |
| cc | 1.4.4 | MIT OR Apache-2.0 | https://github.com/rust-lang/cc-rs | build-time only |
| cesu8 | 1.1.0 | Apache-2.0 OR MIT | https://github.com/emk/cesu8-rs |  |
| cexpr | 0.6.0 | Apache-2.0 OR MIT | https://github.com/jethrogb/rust-cexpr | build-time only |
| cfg-if | 1.0.4 | MIT OR Apache-2.0 | https://github.com/rust-lang/cfg-if |  |
| cfg_aliases | 0.2.2 | MIT | https://github.com/katharostech/cfg_aliases | build-time only |
| chacha20 | 0.10.2 | MIT OR Apache-2.0 | https://github.com/RustCrypto/stream-ciphers |  |
| clang-sys | 1.9.1 | Apache-2.0 | https://github.com/KyleMayes/clang-sys | build-time only |
| colorchoice | 1.0.5 | MIT OR Apache-2.0 | https://github.com/rust-cli/anstyle |  |
| combine | 4.6.8 | MIT | https://github.com/Marwes/combine |  |
| core-foundation-sys | 0.8.7 | MIT OR Apache-2.0 | https://github.com/servo/core-foundation-rs |  |
| coreaudio-rs | 0.11.3 | MIT OR Apache-2.0 | https://github.com/RustAudio/coreaudio-rs |  |
| coreaudio-sys | 0.2.18 | MIT | https://github.com/RustAudio/coreaudio-sys |  |
| cpal | 0.15.3 | Apache-2.0 | https://github.com/rustaudio/cpal |  |
| cpufeatures | 0.3.1 | MIT OR Apache-2.0 | https://github.com/RustCrypto/utils |  |
| crc32c | 0.6.8 | Apache-2.0 OR MIT | https://github.com/zowens/crc32c |  |
| crc32fast | 1.5.1 | MIT OR Apache-2.0 | https://github.com/srijs/rust-crc32fast |  |
| dasp_sample | 0.11.0 | MIT OR Apache-2.0 | https://github.com/rustaudio/sample |  |
| defmt | 1.1.1 | MIT OR Apache-2.0 | https://github.com/knurling-rs/defmt |  |
| defmt-macros | 1.1.1 | MIT OR Apache-2.0 | https://github.com/knurling-rs/defmt |  |
| defmt-parser | 1.0.0 | MIT OR Apache-2.0 | https://github.com/knurling-rs/defmt |  |
| displaydoc | 0.2.7 | MIT OR Apache-2.0 | https://github.com/yaahc/displaydoc |  |
| either | 1.18.0 | MIT OR Apache-2.0 | https://github.com/rayon-rs/either | build-time only |
| env_filter | 2.0.0 | MIT OR Apache-2.0 | https://github.com/rust-cli/env_logger |  |
| env_logger | 0.11.11 | MIT OR Apache-2.0 | https://github.com/rust-cli/env_logger |  |
| equivalent | 1.0.2 | Apache-2.0 OR MIT | https://github.com/indexmap-rs/equivalent |  |
| errno | 0.2.8, 0.3.14 | MIT OR Apache-2.0 | https://github.com/lambda-fairy/rust-errno |  |
| errno-dragonfly | 0.1.2 | MIT | https://github.com/mneumann/errno-dragonfly-rs |  |
| fallible-iterator | 0.3.0 | MIT OR Apache-2.0 | https://github.com/sfackler/rust-fallible-iterator |  |
| fallible-streaming-iterator | 0.1.9 | MIT OR Apache-2.0 | https://github.com/sfackler/fallible-streaming-iterator |  |
| filetime | 0.2.29 | MIT OR Apache-2.0 | https://github.com/alexcrichton/filetime | build-time only |
| find-msvc-tools | 0.1.11 | MIT OR Apache-2.0 | https://github.com/rust-lang/cc-rs | build-time only |
| flate2 | 1.1.10 | MIT OR Apache-2.0 | https://github.com/rust-lang/flate2-rs | build-time only |
| form_urlencoded | 1.2.2 | MIT OR Apache-2.0 | https://github.com/servo/rust-url |  |
| fs2 | 0.4.3 | MIT OR Apache-2.0 | https://github.com/danburkert/fs2-rs |  |
| futures-channel | 0.3.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-core | 0.3.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-io | 0.3.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-macro | 0.3.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-sink | 0.3.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-task | 0.3.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| futures-util | 0.3.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/futures-rs |  |
| getrandom | 0.2.17, 0.4.3 | MIT OR Apache-2.0 | https://github.com/rust-random/getrandom |  |
| glob | 0.3.4 | MIT OR Apache-2.0 | https://github.com/rust-lang/glob | build-time only |
| hashbrown | 0.14.5, 0.17.1 | MIT OR Apache-2.0 | https://github.com/rust-lang/hashbrown |  |
| hashlink | 0.9.1 | MIT OR Apache-2.0 | https://github.com/kyren/hashlink |  |
| http | 1.5.0 | MIT OR Apache-2.0 | https://github.com/hyperium/http |  |
| http-body | 1.1.0 | MIT | https://github.com/hyperium/http-body |  |
| http-body-util | 0.1.5 | MIT | https://github.com/hyperium/http-body |  |
| httparse | 1.10.1 | MIT OR Apache-2.0 | https://github.com/seanmonstar/httparse |  |
| hyper | 1.11.1 | MIT | https://github.com/hyperium/hyper |  |
| hyper-rustls | 0.27.9 | Apache-2.0 OR ISC OR MIT | https://github.com/rustls/hyper-rustls |  |
| hyper-util | 0.1.20 | MIT | https://github.com/hyperium/hyper-util |  |
| icu_collections | 2.3.0 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_locale_core | 2.3.0 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_normalizer | 2.3.0 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_normalizer_data | 2.3.0 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_properties | 2.3.0 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_properties_data | 2.3.0 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| icu_provider | 2.3.1 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| idna | 1.1.0 | MIT OR Apache-2.0 | https://github.com/servo/rust-url/ |  |
| idna_adapter | 1.2.2 | Apache-2.0 OR MIT | https://github.com/hsivonen/idna_adapter |  |
| indexmap | 2.14.1 | Apache-2.0 OR MIT | https://github.com/indexmap-rs/indexmap |  |
| integer-encoding | 3.0.4 | MIT | https://github.com/dermesser/integer-encoding-rs |  |
| ipnet | 2.12.1 | MIT OR Apache-2.0 | https://github.com/krisprice/ipnet |  |
| is_terminal_polyfill | 1.70.2 | MIT OR Apache-2.0 | https://github.com/polyfill-rs/is_terminal_polyfill |  |
| itertools | 0.13.0 | MIT OR Apache-2.0 | https://github.com/rust-itertools/itertools | build-time only |
| itoa | 1.0.18 | MIT OR Apache-2.0 | https://github.com/dtolnay/itoa |  |
| jiff | 0.2.35 | Unlicense OR MIT | https://github.com/BurntSushi/jiff |  |
| jiff-core | 0.1.0 | Unlicense OR MIT | https://github.com/BurntSushi/jiff |  |
| jiff-static | 0.2.35 | Unlicense OR MIT | https://github.com/BurntSushi/jiff |  |
| jni | 0.21.1 | MIT OR Apache-2.0 | https://github.com/jni-rs/jni-rs |  |
| jni-sys | 0.3.1, 0.4.1 | MIT OR Apache-2.0 | https://github.com/jni-rs/jni-sys |  |
| jni-sys-macros | 0.4.1 | MIT OR Apache-2.0 | https://github.com/jni-rs/jni-sys |  |
| jobserver | 0.1.35 | MIT OR Apache-2.0 | https://github.com/rust-lang/jobserver-rs | build-time only |
| js-sys | 0.3.104 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/js-sys |  |
| libc | 0.2.178 | MIT OR Apache-2.0 | https://github.com/rust-lang/libc |  |
| libloading | 0.8.9 | ISC | https://github.com/nagisa/rust_libloading/ | build-time only |
| libsqlite3-sys | 0.30.1 | MIT | https://github.com/rusqlite/rusqlite |  |
| linux-raw-sys | 0.12.1 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/sunfishcode/linux-raw-sys | build-time only |
| litemap | 0.8.3 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| log | 0.4.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/log |  |
| lru-slab | 0.1.2 | MIT OR Apache-2.0 OR Zlib | https://github.com/Ralith/lru-slab |  |
| mach2 | 0.4.3 | BSD-2-Clause OR MIT OR Apache-2.0 | https://github.com/JohnTitor/mach2 |  |
| memchr | 2.8.3 | Unlicense OR MIT | https://github.com/BurntSushi/memchr |  |
| minimal-lexical | 0.2.1 | MIT OR Apache-2.0 | https://github.com/Alexhuszagh/minimal-lexical | build-time only |
| miniz_oxide | 0.9.1 | MIT OR Zlib OR Apache-2.0 | https://github.com/Frommi/miniz_oxide/tree/master/miniz_oxide | build-time only |
| mio | 1.2.2 | MIT | https://github.com/tokio-rs/mio |  |
| ndk | 0.8.0 | MIT OR Apache-2.0 | https://github.com/rust-mobile/ndk |  |
| ndk-context | 0.1.1 | MIT OR Apache-2.0 | https://github.com/rust-windowing/android-ndk-rs |  |
| ndk-sys | 0.5.0+25.2.9519653 | MIT OR Apache-2.0 | https://github.com/rust-mobile/ndk |  |
| nom | 7.1.3 | MIT | https://github.com/Geal/nom | build-time only |
| num-derive | 0.4.2 | MIT OR Apache-2.0 | https://github.com/rust-num/num-derive |  |
| num-traits | 0.2.19 | MIT OR Apache-2.0 | https://github.com/rust-num/num-traits |  |
| num_enum | 0.7.6 | BSD-3-Clause OR MIT OR Apache-2.0 | https://github.com/illicitonion/num_enum |  |
| num_enum_derive | 0.7.6 | BSD-3-Clause OR MIT OR Apache-2.0 | https://github.com/illicitonion/num_enum |  |
| oboe | 0.6.1 | Apache-2.0 | https://github.com/katyo/oboe-rs |  |
| oboe-sys | 0.6.1 | Apache-2.0 | https://github.com/katyo/oboe-rs |  |
| once_cell | 1.21.4 | MIT OR Apache-2.0 | https://github.com/matklad/once_cell |  |
| once_cell_polyfill | 1.70.2 | MIT OR Apache-2.0 | https://github.com/polyfill-rs/once_cell_polyfill |  |
| percent-encoding | 2.3.2 | MIT OR Apache-2.0 | https://github.com/servo/rust-url/ |  |
| pin-project-lite | 0.2.17 | Apache-2.0 OR MIT | https://github.com/taiki-e/pin-project-lite |  |
| pkg-config | 0.3.34 | MIT OR Apache-2.0 | https://github.com/rust-lang/pkg-config-rs | build-time only |
| portable-atomic | 1.15.0 | Apache-2.0 OR MIT | https://github.com/taiki-e/portable-atomic |  |
| portable-atomic-util | 0.2.7 | Apache-2.0 OR MIT | https://github.com/taiki-e/portable-atomic-util |  |
| potential_utf | 0.1.6 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| ppv-lite86 | 0.2.21 | MIT OR Apache-2.0 | https://github.com/cryptocorrosion/cryptocorrosion |  |
| proc-macro-crate | 3.5.0 | MIT OR Apache-2.0 | https://github.com/bkchr/proc-macro-crate |  |
| proc-macro2 | 1.0.107 | MIT OR Apache-2.0 | https://github.com/dtolnay/proc-macro2 |  |
| quinn | 0.11.11 | MIT OR Apache-2.0 | https://github.com/quinn-rs/quinn |  |
| quinn-proto | 0.11.17 | MIT OR Apache-2.0 | https://github.com/quinn-rs/quinn |  |
| quinn-udp | 0.5.15 | MIT OR Apache-2.0 | https://github.com/quinn-rs/quinn |  |
| quote | 1.0.47 | MIT OR Apache-2.0 | https://github.com/dtolnay/quote |  |
| r-efi | 6.0.0 | MIT OR Apache-2.0 OR LGPL-2.1-or-later | https://github.com/r-efi/r-efi |  |
| rand | 0.10.2, 0.8.8 | MIT OR Apache-2.0 | https://github.com/rust-random/rand |  |
| rand_chacha | 0.3.1 | MIT OR Apache-2.0 | https://github.com/rust-random/rand |  |
| rand_core | 0.10.1, 0.6.4 | MIT OR Apache-2.0 | https://github.com/rust-random/rand |  |
| rand_pcg | 0.10.2 | MIT OR Apache-2.0 | https://github.com/rust-random/rngs |  |
| regex | 1.13.1 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |  |
| regex-automata | 0.4.18 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |  |
| regex-syntax | 0.8.11 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |  |
| reqwest | 0.12.28 | MIT OR Apache-2.0 | https://github.com/seanmonstar/reqwest |  |
| ring | 0.17.14 | Apache-2.0 AND ISC | https://github.com/briansmith/ring |  |
| rusqlite | 0.32.1 | MIT | https://github.com/rusqlite/rusqlite |  |
| rustc-hash | 2.1.3 | Apache-2.0 OR MIT | https://github.com/rust-lang/rustc-hash |  |
| rustc_version | 0.4.1 | MIT OR Apache-2.0 | https://github.com/djc/rustc-version-rs | build-time only |
| rustix | 1.1.4 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/bytecodealliance/rustix | build-time only |
| rustls | 0.23.43 | Apache-2.0 OR ISC OR MIT | https://github.com/rustls/rustls |  |
| rustls-pki-types | 1.15.1 | MIT OR Apache-2.0 | https://github.com/rustls/pki-types |  |
| rustls-webpki | 0.103.15 | ISC | https://github.com/rustls/webpki |  |
| rustversion | 1.0.23 | MIT OR Apache-2.0 | https://github.com/dtolnay/rustversion |  |
| rusty-leveldb | 4.0.1 | MIT | https://github.com/dermesser/leveldb-rs |  |
| ryu | 1.0.23 | Apache-2.0 OR BSL-1.0 | https://github.com/dtolnay/ryu |  |
| same-file | 1.0.6 | Unlicense OR MIT | https://github.com/BurntSushi/same-file | build-time only |
| semver | 1.0.28 | MIT OR Apache-2.0 | https://github.com/dtolnay/semver | build-time only |
| serde | 1.0.229 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |  |
| serde_core | 1.0.229 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |  |
| serde_derive | 1.0.229 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |  |
| serde_json | 1.0.151 | MIT OR Apache-2.0 | https://github.com/serde-rs/json |  |
| serde_urlencoded | 0.7.1 | MIT OR Apache-2.0 | https://github.com/nox/serde_urlencoded |  |
| sherpa-onnx | 1.13.6 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |  |
| sherpa-onnx-sys | 1.13.6 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |  |
| shlex | 1.3.0, 2.0.1 | MIT OR Apache-2.0 | https://github.com/comex/rust-shlex | build-time only |
| simd-adler32 | 0.3.10 | MIT | https://github.com/mcountryman/simd-adler32 | build-time only |
| slab | 0.4.12 | MIT | https://github.com/tokio-rs/slab |  |
| smallvec | 1.15.2 | MIT OR Apache-2.0 | https://github.com/servo/rust-smallvec |  |
| snap | 1.1.2 | BSD-3-Clause | https://github.com/BurntSushi/rust-snappy |  |
| socket2 | 0.6.5 | MIT OR Apache-2.0 | https://github.com/rust-lang/socket2 |  |
| stable_deref_trait | 1.2.1 | MIT OR Apache-2.0 | https://github.com/storyyeller/stable_deref_trait |  |
| subtle | 2.6.1 | BSD-3-Clause | https://github.com/dalek-cryptography/subtle |  |
| syn | 2.0.119, 3.0.4 | MIT OR Apache-2.0 | https://github.com/dtolnay/syn |  |
| sync_wrapper | 1.0.2 | Apache-2.0 | https://github.com/Actyx/sync_wrapper |  |
| synstructure | 0.13.2 | MIT | https://github.com/mystor/synstructure |  |
| tar | 0.4.46 | MIT OR Apache-2.0 | https://github.com/composefs/tar-rs | build-time only |
| thiserror | 1.0.69, 2.0.20 | MIT OR Apache-2.0 | https://github.com/dtolnay/thiserror |  |
| thiserror-impl | 1.0.69, 2.0.20 | MIT OR Apache-2.0 | https://github.com/dtolnay/thiserror |  |
| tinystr | 0.8.4 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| tinyvec | 1.12.0 | Zlib OR Apache-2.0 OR MIT | https://github.com/Lokathor/tinyvec |  |
| tinyvec_macros | 0.1.1 | MIT OR Apache-2.0 OR Zlib | https://github.com/Soveu/tinyvec_macros |  |
| tokio | 1.53.1 | MIT | https://github.com/tokio-rs/tokio |  |
| tokio-macros | 2.7.2 | MIT | https://github.com/tokio-rs/tokio |  |
| tokio-rustls | 0.26.4 | MIT OR Apache-2.0 | https://github.com/rustls/tokio-rustls |  |
| tokio-util | 0.7.19 | MIT | https://github.com/tokio-rs/tokio |  |
| toml_datetime | 1.1.1+spec-1.1.0 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| toml_edit | 0.25.13+spec-1.1.0 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| toml_parser | 1.1.3+spec-1.1.0 | MIT OR Apache-2.0 | https://github.com/toml-rs/toml |  |
| tower | 0.5.3 | MIT | https://github.com/tower-rs/tower |  |
| tower-http | 0.6.11 | MIT | https://github.com/tower-rs/tower-http |  |
| tower-layer | 0.3.3 | MIT | https://github.com/tower-rs/tower |  |
| tower-service | 0.3.3 | MIT | https://github.com/tower-rs/tower |  |
| tracing | 0.1.44 | MIT | https://github.com/tokio-rs/tracing |  |
| tracing-core | 0.1.36 | MIT | https://github.com/tokio-rs/tracing |  |
| try-lock | 0.2.5 | MIT | https://github.com/seanmonstar/try-lock |  |
| unicode-ident | 1.0.24 | (MIT OR Apache-2.0) AND Unicode-3.0 | https://github.com/dtolnay/unicode-ident |  |
| untrusted | 0.9.0 | ISC | https://github.com/briansmith/untrusted |  |
| ureq | 2.12.1 | MIT OR Apache-2.0 | https://github.com/algesten/ureq | build-time only |
| url | 2.5.8 | MIT OR Apache-2.0 | https://github.com/servo/rust-url |  |
| utf8_iter | 1.0.4 | Apache-2.0 OR MIT | https://github.com/hsivonen/utf8_iter |  |
| utf8parse | 0.2.2 | Apache-2.0 OR MIT | https://github.com/alacritty/vte |  |
| vcpkg | 0.2.15 | MIT OR Apache-2.0 | https://github.com/mcgoo/vcpkg-rs | build-time only |
| version_check | 0.9.5 | MIT OR Apache-2.0 | https://github.com/SergioBenitez/version_check | build-time only |
| walkdir | 2.5.0 | Unlicense OR MIT | https://github.com/BurntSushi/walkdir | build-time only |
| want | 0.3.1 | MIT | https://github.com/seanmonstar/want |  |
| wasi | 0.11.1+wasi-snapshot-preview1 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/bytecodealliance/wasi |  |
| wasm-bindgen | 0.2.127 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen |  |
| wasm-bindgen-futures | 0.4.77 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/futures |  |
| wasm-bindgen-macro | 0.2.127 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/macro |  |
| wasm-bindgen-macro-support | 0.2.127 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/macro-support |  |
| wasm-bindgen-shared | 0.2.127 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/shared |  |
| wasm-streams | 0.4.2 | MIT OR Apache-2.0 | https://github.com/MattiasBuelens/wasm-streams/ |  |
| web-sys | 0.3.104 | MIT OR Apache-2.0 | https://github.com/wasm-bindgen/wasm-bindgen/tree/master/crates/web-sys |  |
| web-time | 1.1.0 | MIT OR Apache-2.0 | https://github.com/daxpedda/web-time |  |
| webpki-roots | 0.26.11, 1.0.9 | CDLA-Permissive-2.0 | https://github.com/rustls/webpki-roots |  |
| winapi | 0.3.9 | MIT OR Apache-2.0 | https://github.com/retep998/winapi-rs |  |
| winapi-i686-pc-windows-gnu | 0.4.0 | MIT OR Apache-2.0 | https://github.com/retep998/winapi-rs |  |
| winapi-util | 0.1.11 | Unlicense OR MIT | https://github.com/BurntSushi/winapi-util | build-time only |
| winapi-x86_64-pc-windows-gnu | 0.4.0 | MIT OR Apache-2.0 | https://github.com/retep998/winapi-rs |  |
| windows | 0.54.0 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-core | 0.54.0 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-link | 0.2.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-result | 0.1.2 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-sys | 0.61.2 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows-targets | 0.42.2, 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_aarch64_gnullvm | 0.42.2, 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_aarch64_msvc | 0.42.2, 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_i686_gnu | 0.42.2, 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_i686_gnullvm | 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_i686_msvc | 0.42.2, 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_x86_64_gnu | 0.42.2, 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_x86_64_gnullvm | 0.42.2, 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| windows_x86_64_msvc | 0.42.2, 0.52.6 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |  |
| winnow | 1.0.4 | MIT | https://github.com/winnow-rs/winnow |  |
| writeable | 0.6.4 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| xattr | 1.6.1 | MIT OR Apache-2.0 | https://github.com/Stebalien/xattr | build-time only |
| yoke | 0.8.3 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| yoke-derive | 0.8.2 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zerocopy | 0.8.56 | BSD-2-Clause OR Apache-2.0 OR MIT | https://github.com/google/zerocopy |  |
| zerocopy-derive | 0.8.56 | BSD-2-Clause OR Apache-2.0 OR MIT | https://github.com/google/zerocopy |  |
| zerofrom | 0.1.8 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zerofrom-derive | 0.1.7 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zeroize | 1.9.0 | Apache-2.0 OR MIT | https://github.com/RustCrypto/utils |  |
| zerotrie | 0.2.5 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zerovec | 0.11.8 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zerovec-derive | 0.11.6 | Unicode-3.0 | https://github.com/unicode-org/icu4x |  |
| zlib-rs | 0.6.7 | Zlib | https://github.com/trifectatechfoundation/zlib-rs | build-time only |
| zmij | 1.0.23 | MIT | https://github.com/dtolnay/zmij |  |
<!-- END GENERATED: rust -->

## Local document rendering resources

- [Liberation Fonts](https://github.com/liberationfonts/liberation-fonts),
  bundled in `backend/render_fonts`, provide the default sans, serif and
  monospace document fonts (regular, bold, italic and bold italic).
  Licensed under SIL Open Font License 1.1; the full license and copyright
  notices are included in `backend/render_fonts/LICENSE`.
- [Playwright](https://github.com/microsoft/playwright) (Apache-2.0) and one
  [Chromium headless shell](https://www.chromium.org/) (BSD-style and its bundled
  third-party licenses) are included only in the Linux server image. Desktop
  rendering reuses Electron. The distributions retain their license files.
- `packaging/headless/render-seccomp.json` is derived from the
  [Moby default seccomp profile](https://github.com/moby/profiles/blob/main/seccomp/default.json)
  (Apache-2.0), with user namespace creation permitted for Chromium's sandbox.
