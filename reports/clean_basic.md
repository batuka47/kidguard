# clean_basic report

Rules: PIL verify, RGB conversion, short side >= 128 px, grayscale std >= 5.0. Kept files re-saved as RGB JPEG q=92, long side <= 512 px.

| class | verify_failed | not_rgb | too_small | single_colour | missing | keep | reencode (convert) | reencode (resize) | total |
|---|---|---|---|---|---|---|---|---|---|
| safe | 0 | 0 | 96 | 0 | 0 | 37789 | 0 | 0 | 37885 |
| nudity | 0 | 0 | 6 | 0 | 0 | 26400 | 0 | 0 | 26406 |
| violence | 0 | 0 | 0 | 0 | 0 | 3607 | 0 | 0 | 3607 |
| gore | 0 | 0 | 0 | 0 | 0 | 967 | 0 | 0 | 967 |
| **total** | 0 | 0 | 102 | 0 | 0 | 68763 | 0 | 0 | 68865 |

Rejected per source:

- adult_content: too_small 48
- nsfw_detect: too_small 20
- unsafebench: too_small 34

metadata.csv: 68865 rows before, 68763 after (this run).

## All runs: files in data/interim/rejected/

| class | verify_failed | not_rgb | too_small | single_colour | total |
|---|---|---|---|---|---|
| safe | 0 | 0 | 825 | 17 | 842 |
| nudity | 0 | 3 | 263 | 3 | 269 |
| gore | 0 | 0 | 33 | 0 | 33 |
| **total** | 0 | 3 | 1121 | 20 | 1144 |
