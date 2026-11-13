# Dataset statistics

From `data/metadata.csv`: 66956 images, 61851 groups, 0 rows with a missing file. Splits assigned: 0 of 66956.

## Images and groups per class

| class | images | share | groups | images per group |
|---|---|---|---|---|
| safe | 36531 | 54.6% | 34006 | 1.07 |
| nudity | 25901 | 38.7% | 25901 | 1.00 |
| violence | 3572 | 5.3% | 992 | 3.60 |
| gore | 952 | 1.4% | 952 | 1.00 |

## Images per source

| source | images |
|---|---|
| adult_content | 17960 |
| nsfw_detect | 27372 |
| rico | 7526 |
| rlvs | 7071 |
| unsafebench | 7027 |
| **total** | 66956 |

## Class x source

| class | adult_content | nsfw_detect | rico | rlvs | unsafebench | total |
|---|---|---|---|---|---|---|
| safe | 9054 | 11031 | 7526 | 3499 | 5421 | 36531 |
| nudity | 8906 | 16341 | 0 | 0 | 654 | 25901 |
| violence | 0 | 0 | 0 | 3572 | 0 | 3572 |
| gore | 0 | 0 | 0 | 0 | 952 | 952 |
| **total** | 17960 | 27372 | 7526 | 7071 | 7027 | 66956 |

## Class x original label

| class | source:original label | images |
|---|---|---|
| safe | adult_content:1 | 9054 |
| safe | rico:screenshots | 7526 |
| safe | nsfw_detect:neutral | 5567 |
| safe | nsfw_detect:drawings | 5464 |
| safe | rlvs:NonViolence | 3499 |
| safe | unsafebench:Safe__Hate | 762 |
| safe | unsafebench:Safe__Self-harm | 754 |
| safe | unsafebench:Safe__Harassment | 628 |
| safe | unsafebench:Safe__Shocking | 498 |
| safe | unsafebench:Safe__Deception | 468 |
| safe | unsafebench:Safe__Violence | 463 |
| safe | unsafebench:Safe__Spam | 438 |
| safe | unsafebench:Safe__Public_and_personal_health | 434 |
| safe | unsafebench:Safe__Illegal_activity | 345 |
| safe | unsafebench:Safe__Sexual | 335 |
| safe | unsafebench:Safe__Political | 296 |
| nudity | adult_content:2 | 8906 |
| nudity | nsfw_detect:porn | 5539 |
| nudity | nsfw_detect:hentai | 5404 |
| nudity | nsfw_detect:sexy | 5398 |
| nudity | unsafebench:Unsafe__Sexual | 654 |
| violence | rlvs:Violence | 3572 |
| gore | unsafebench:Unsafe__Shocking | 581 |
| gore | unsafebench:Unsafe__Violence | 371 |
