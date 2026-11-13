# dedup report

phash 64-bit, near duplicate = Hamming distance <= 5; max 4 near-identical frames per group.

Near pairs found: 3552 (by distance: {0: 1155, 2: 965, 4: 1432}).

| class | label_conflict | dup | dup_in_group | kept | total |
|---|---|---|---|---|---|
| safe | 21 | 1237 | 0 | 36531 | 37789 |
| nudity | 10 | 489 | 0 | 25901 | 26400 |
| violence | 4 | 31 | 0 | 3572 | 3607 |
| gore | 12 | 3 | 0 | 952 | 967 |
| **total** | 47 | 1760 | 0 | 66956 | 68763 |

| source | label_conflict | dup | dup_in_group | kept |
|---|---|---|---|---|
| adult_content | 0 | 150 | 0 | 17960 |
| nsfw_detect | 8 | 597 | 0 | 27372 |
| rico | 0 | 473 | 0 | 7526 |
| rlvs | 8 | 357 | 0 | 7071 |
| unsafebench | 31 | 183 | 0 | 7027 |

## Label conflicts: 26 pairs, 47 images moved

- 9 pairs: gore vs safe (unsafebench / unsafebench)
- 6 pairs: safe vs violence (rlvs / rlvs)
- 4 pairs: nudity vs safe (nsfw_detect / nsfw_detect)
- 4 pairs: nudity vs safe (unsafebench / unsafebench)
- 3 pairs: gore vs nudity (unsafebench / unsafebench)

| image A | label A | image B | label B | distance |
|---|---|---|---|---|
| `unsafebench_test_00415.jpg` | gore | `unsafebench_train_03913.jpg` | safe | 0 |
| `unsafebench_test_01339.jpg` | gore | `unsafebench_train_06171.jpg` | safe | 0 |
| `unsafebench_test_01716.jpg` | gore | `unsafebench_test_01248.jpg` | safe | 0 |
| `unsafebench_train_04382.jpg` | gore | `unsafebench_test_01735.jpg` | safe | 0 |
| `unsafebench_train_04476.jpg` | gore | `unsafebench_train_04811.jpg` | safe | 0 |
| `unsafebench_train_04507.jpg` | gore | `unsafebench_train_05085.jpg` | nudity | 0 |
| `unsafebench_train_04533.jpg` | gore | `unsafebench_train_05394.jpg` | nudity | 0 |
| `unsafebench_train_04562.jpg` | gore | `unsafebench_train_05771.jpg` | safe | 0 |
| `unsafebench_train_05878.jpg` | gore | `unsafebench_train_03619.jpg` | safe | 0 |
| `unsafebench_train_05912.jpg` | gore | `unsafebench_train_03592.jpg` | safe | 0 |
| `unsafebench_train_08090.jpg` | gore | `unsafebench_test_00642.jpg` | nudity | 0 |
| `nsfw_detect_04f902b994c68ac97810bf6359f0b226b5f4c9e81e1a71dd8b10d8e47d89e1dc.jpg` | nudity | `nsfw_detect_adc9450013ef4e8d30f6bc14f824e538c350b29e37542f66bed14fe05f708c72.jpg` | safe | 0 |
| `nsfw_detect_785ff38d722c9b9e509ed6351340a0ce3b0d3c64f55b894c77fca46fc8b9b27f.jpg` | nudity | `nsfw_detect_785ff38d722c9b9e509ed6351340a0ce3b0d3c64f55b894c77fca46fc8b9b27f.jpg` | safe | 0 |
| `nsfw_detect_73300d3ab1e51762.jpg` | nudity | `nsfw_detect_ea856a900253ea28f1c5afa68214d4c94db0b86473878dbe0831985b17eebaff.jpg` | safe | 0 |
| `nsfw_detect_bc157b79f7513ee677fddf68c0cd35b1bfb892a13097216f35298d3a88e0d2b8.jpg` | nudity | `nsfw_detect_8cb8b45c875e40eb2ce5615aa09aac7f47e02d63206d33c738f39f310aeff182.jpg` | safe | 0 |
| `unsafebench_test_01601.jpg` | nudity | `unsafebench_train_04226.jpg` | safe | 0 |
| `unsafebench_test_01601.jpg` | nudity | `unsafebench_train_06417.jpg` | safe | 0 |
| `unsafebench_train_01054.jpg` | nudity | `unsafebench_train_07925.jpg` | safe | 0 |
| `rlvs_NV_226_f032.jpg` | safe | `rlvs_V_504_f032.jpg` | violence | 0 |
| `rlvs_NV_226_f064.jpg` | safe | `rlvs_V_504_f064.jpg` | violence | 0 |
| `rlvs_NV_226_f097.jpg` | safe | `rlvs_V_504_f097.jpg` | violence | 0 |
| `rlvs_NV_226_f129.jpg` | safe | `rlvs_V_504_f129.jpg` | violence | 0 |
| `unsafebench_train_00030.jpg` | gore | `unsafebench_train_07920.jpg` | safe | 2 |
| `unsafebench_train_05283.jpg` | nudity | `unsafebench_test_01833.jpg` | safe | 4 |
| `rlvs_NV_226_f032.jpg` | safe | `rlvs_V_504_f064.jpg` | violence | 4 |
| `rlvs_NV_226_f064.jpg` | safe | `rlvs_V_504_f032.jpg` | violence | 4 |

metadata.csv: 68763 rows before, 66956 after.
