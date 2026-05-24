# NOTICE

## paper-search-pro

Copyright 2026 Bo

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this file except in compliance with the License. You may obtain
a copy of the License at:

  <http://www.apache.org/licenses/LICENSE-2.0>

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

---

## Vendored Code

This project incorporates code and design patterns adapted from upstream
open source projects. Per Apache License 2.0 §4.b, modifications are
documented and the original license, copyright, and attribution notices
are preserved.

### paper-qa (Apache License 2.0)

Portions of the deterministic helper code under `scripts/` and the
retry utility at `scripts/vendored/tenacity_retry.py` are adapted from
FutureHouse's paper-qa project.

| | |
|---|---|
| **Project** | paper-qa (also known as PaperQA / PaperQA2) |
| **Repository** | <https://github.com/Future-House/paper-qa> |
| **License** | Apache License 2.0 |
| **License copy** | [`scripts/vendored/LICENSE-paperqa.txt`](scripts/vendored/LICENSE-paperqa.txt) |
| **Modifications log** | [`scripts/vendored/README-vendored.md`](scripts/vendored/README-vendored.md) |
| **Reviewed at** | main branch as of 2026-05-19 |

The combined work is licensed under the Apache License 2.0. The vendored
subset remains subject to its original Apache 2.0 terms; the project-
specific orchestration, the React report renderer, and the dual-language
UI are original to paper-search-pro.

---

## Project Scaffold

The React-based HTML report viewer at `assets/webartifacts_app/paper-report/`
was bootstrapped via Anthropic's **Web Artifacts Builder** Claude Code
Skill, which provides the single-file-HTML compile pattern (Vite +
`html-inline`). The Skill's scaffold output is owned by the project per
Anthropic's Skill terms; this acknowledgment is provided as good practice
rather than a legal requirement.

---

See [`THIRD_PARTY.md`](THIRD_PARTY.md) for a non-exhaustive list of third-
party open source libraries bundled into the compiled `bundle.html` and
imported via the Python runtime.
