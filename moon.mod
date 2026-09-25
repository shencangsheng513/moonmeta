// moon.mod 的各项含义：
// https://docs.moonbitlang.com/en/latest/toolchain/moon/module.html

name = "shencangsheng513/moonmeta"

version = "0.1.0"

readme = "README.mbt.md"

repository = ""

license = "Apache-2.0"

keywords = [
  "exif",
  "metadata",
  "jpeg",
  "png",
  "tiff",
  "gps",
  "privacy",
  "redaction",
]

preferred_target = "wasm"

description = "Read, write and redact EXIF metadata in JPEG, PNG and TIFF files, in pure MoonBit."

import {
  "moonbitlang/x@0.5.5",
}
