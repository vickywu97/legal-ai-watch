# ✗F 范围外规范：人工核验官方原文模板

`config/article_texts.json` 的 38 条正文全部取自
`legal-hallucination-bench` 的已核验 KB（8 部法）。但 39 题的标准答案里，
有 **22 个法条引用落在 8 部法之外**，目前 ✗F 对它们一律跳过（`_uncovered`）。
要把这些也纳入 ✗F 覆盖，需要**律师逐条从官方原文核对填入**——脚本绝不代写
任何法条文字（那正是本基准要检测的幻觉）。

## 缺口分布（22 条）

| 规范 | 条数 | 性质 | 官方出处 |
|---|---|---|---|
| 个人所得税专项附加扣除暂行办法 | 18（#5–#22） | 国务院规范性文件（国发〔2018〕41号） | 中国政府网 www.gov.cn |
| 个人信息保护法 | 2（#38, #54） | 法律（主席令第六十一号，2021） | 国家法律法规数据库 flk.npc.gov.cn |
| 反不正当竞争法 | 1（#6） | 法律（2019 修正） | 国家法律法规数据库 flk.npc.gov.cn |
| 数据安全法 | 1（#27） | 法律（主席令第八十四号，2021） | 国家法律法规数据库 flk.npc.gov.cn |

## 工作流（三步）

```bash
# 1) 生成/更新留空模板（幂等，保留你已填的内容）
python scripts/build_article_texts.py --emit-pending config/article_texts_unverified.json

# 2) 在 config/article_texts_unverified.json 里：
#    - 把 article_texts["<law>#<article>"] 填为该条【官方全文】
#    - 把 _pending 中对应条的 "status" 改为 "VERIFIED"
#    （建议逐条在 flk.npc.gov.cn / www.gov.cn 核对令号与施行日期）

# 3) 合并进主库（仅接受 VERIFIED 且正文非空者；主库 _uncovered 同步减少）
python scripts/build_article_texts.py --merge-pending config/article_texts_unverified.json
```

合并安全闸：只合并显式 `VERIFIED` 的条目；**已填但未置 VERIFIED 的会跳过并打印警告**，
避免把未核实文字当官方标准答案。合并后该条在模板中置 `MERGED` 并清空，主库重生成时
（普通 `build_article_texts.py` 不带参数）仍会保留这些人工核验条目。

## 逐条清单（被哪些题引用）

```
个人信息保护法#38    <- Q24(预期解)
个人信息保护法#54    <- Q24(预期解)        [注：Q24 同时引 #38 与 #54]
个人所得税专项附加扣除暂行办法#5  ~ #22     <- Q11–Q22 等（专项附加扣除各情形）
反不正当竞争法#6     <- （混淆行为认定相关题）
数据安全法#27       <- Q26(预期解)
```

> 精确被引题号见 `config/article_texts_unverified.json` 各条 `cited_by` 字段。

## 建议填写顺序

1. **个人所得税专项附加扣除暂行办法 #5–#22**（18 条，占比最大）：国务院文件，
   中国政府网有官方全文，逐条复制即可，工作量集中但来源单一。
2. **个人信息保护法 #38 / #54**、**数据安全法 #27**、**反不正当竞争法 #6**：
   法律条文，国家法律法规数据库可查。

填完一批就合并一批，不必一次填完 22 条——`--emit-pending` 幂等，随时可补。
