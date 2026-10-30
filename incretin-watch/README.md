# Incretin Watch｜全球肠促胰素药物进展

为礼来（Eli Lilly）和诺和诺德（Novo Nordisk）的肠促胰素产品自动整理重要进展，输出可追溯的 Markdown 简报、JSON、CSV。包括新适应证/监管审评、政策、安全性、当地上市、重大临床证据、价格/供给及竞争事件。

默认每天北京时间 **08:17** 在 GitHub Actions 执行，回看 14 天；GitHub 定时任务不保证准点。还可在 Actions → **Incretin market watch** → **Run workflow** 手动运行。代码推入 `main` 时执行任务，报告提交不会再次触发采集。

## 直接查看

- [最新简报](reports/latest.md)、[JSON](reports/latest.json)、[CSV](reports/latest.csv)
- `reports/YYYY-MM-DD/`：每次运行的独立历史快照，同一天重跑不会覆盖前一份。
- [来源健康状态](reports/coverage.json)：失败、窗口不足和文章正文获取失败均列出。
- `state/state.json`：跨天、跨机器运行的去重状态。请与报告一起保留。

## 两种分析模式

**无需密钥即可运行。** `rules` 模式提取原文标题与短摘录，标明来源身份，按事件类别提供产品竞争力、临床应用、未来市场三个维度的条件性分析。原文摘录不会自动翻译；模板不等于针对每篇研究的专家精读。

如需逐事件中文归纳，在仓库 Settings → Secrets and variables → Actions 中添加：

| 位置 | 名称 | 内容 |
|---|---|---|
| Repository secret | `OPENAI_API_KEY` | 你的 OpenAI API 密钥 |
| Repository variable | `OPENAI_MODEL` | 账户中可用、支持 Responses API 与 JSON Schema 的文本模型 ID |

自动模式仅在这两项都存在时调用模型。每次最多分析 15 个事件，可在 `config.json` 修改；其余事件照常输出规则结果。无密钥不产生模型费用。模型模式会把所选公开来源的正文片段发送给 OpenAI；请求设置 `store: false`。**不要把密钥放入代码、配置、报告或 Issue。**

模型生成的事实必须附有效来源 ID 和原文连续证据片段，程序校验引用是否存在；日期还需原文日期证据。模型拒绝、超时、输出不完整、引用校验失败均回退规则模式并在报告说明。引用匹配不能证明语义蕴含；中文归纳和分析仍需人工复核。本项目没有在仓库中预置密钥。

## 本地运行

Python 3.11+，Linux/macOS（Windows 可使用 WSL）。

```bash
git clone https://github.com/ysm19990103/market_monitoring.git
cd market_monitoring/incretin-watch
python -m venv .venv
source .venv/bin/activate
python -m pip install .
incretin-watch --analysis rules
```

```bash
# 只检查部分来源；状态仍然保留
incretin-watch --sources lilly,novo,fda_press,ema_news,europepmc --lookback-days 30

# 单独历史回看，避免影响日常去重状态
incretin-watch --as-of 2026-10-30 --lookback-days 14 --state .cache/backfill-state.json --output .cache/backfill-reports

# 已在环境中设置 OPENAI_API_KEY 和 OPENAI_MODEL 后
incretin-watch --analysis llm

python -m unittest discover -s tests -v
```

`--strict-coverage` 在任一来源失败或部分覆盖时返回非零状态；默认继续生成有明确缺口说明的报告。所有来源失败时返回 2，不推进去重状态、不生成“无新进展”结论。源文件解析或状态结构异常会使任务失败，不能静默重建状态而重复报送。

## 来源与地域

| 来源类别 | 默认入口 | 覆盖边界 |
|---|---|---|
| 公司官方 | Lilly RSS；Novo 官方新闻档案公开接口 | 公司自己的披露；财务/研究结果尚需核对独立研究或监管文件 |
| 美国 | FDA 新闻、安全通报、GLP-1 配制政策及未批准产品风险；CMS 公告 | FDA/CMS 指定入口，不等于所有标签、诉讼或州级政策 |
| 欧洲 | EMA 新闻、EPAR/意见；英国 MHRA 新闻及安全更新 | CHMP 意见单独标记，不等于欧盟委员会最终许可 |
| 亚洲 | NMPA 药品监管动态；PMDA 安全通知 | 当前列表；访问限制或语言/页面变更可能形成缺口 |
| 其他 | TGA、Health Canada、ANVISA | 当前安全/新闻入口，非全部批准数据库 |
| 原始研究 | Europe PMC 检索 MED/PubMed 原始研究摘要 | 首次发表/首次收录窗口；不把索引检索等同于已读取论文全文 |

默认 17 个来源入口。所有文章链接均限制在配置中的官方域名；跳转离开白名单会被拒绝。优先使用官方来源，并保留论文 DOI/PMID。遵守网站访问限制，不绕过 CAPTCHA、登录或付费墙。**全球是关注范围，不是穷尽覆盖承诺**；新来源可以通过 `config.json` 加入。

主要产品检索包含 Mounjaro、Zepbound、Trulicity、Foundayo、Ozempic、Wegovy、Rybelsus、Victoza、Saxenda 和含利拉鲁肽的复方 Xultophy，以及常用中文/日文名称。药物列表是发现词表，不是每个地区/适应证的实时许可数据库。为避免漏掉竞争变化，也发现 mazdutide、ecnoglutide 等当地产品及部分重要在研竞品；不据此推定其全球已上市。产品词表检查日：2026-10-30。

首次运行不会将没有可靠日期的旧网页包装成今日新闻。FDA 滚动更新页面先建立基线，后续相关正文变化单独标为“页面内容变更”，不会自动视作新的批准。

## 日期、证据和影响判断

- `event_date`：事件发生日，无法确认则为空；`published_date`：公告/论文发表日；`modified_date`：页面修改日；抓取日期另记，彼此不替换。
- “监管机构记载”“公司披露”“研究摘要报告”分开显示。通过原始研究索引发现的记录仍是摘要级证据；预印本不在默认 MED 检索内，综述/社论不作为原始研究入选。
- 临床解读关注研究设计、对照、主要终点、效应量及 CI、随访、人群、estimand。缺失数据不补造，事后分析不写成预设确证性结果。
- 安全信号与因果关系不同。没有暴露分母时，不从自发报告数计算发生率或直接比较产品风险。
- 申请受理、审评积极意见、最终批准、商业上市、会议预告和完整研究结果分别标记。一个品牌/剂型/地区的许可不外推给同成分其他产品。
- 影响字段始终属于推断；不生成未经支持的市场份额、销售额、股价预测或个体处方建议。

## 去重与维护

1. 去掉 URL 跟踪参数，保留 `id` 等文章标识；同 URL 的相关正文版本持久化记录。
2. DOI 合并同一论文；相近日期、阶段、地区、成分、品牌及高度相似标题保守合并转载。
3. 来源增加时把链接补入历史事件；数值不同、新随访、不同地区/阶段/人群不强行合并。
4. 相关正文的新版本可再报，并明确只是内容更新。未能读取正文的记录不标为已报，后续运行重试。
5. 先成功写报告，再提交去重状态。Actions 串行运行，持久化时不强推覆盖远端更新。

跨语言改写和改换标题仍可能漏合并；相同 URL 的编辑变更也可能触发复核。相似度去重不是已完成的人工事实审查。源站改变结构会通过健康状态显示，适配器和相关测试需要维护。扩展到新的制剂、品牌、监管入口时更新配置和测试。

GitHub Actions 需要仓库允许 Actions 和 `contents: write`；分支保护可能阻止自动提交。任务总时限 30 分钟，具体可用额度取决于 GitHub 账户和仓库设置。如写回失败，已生成的本次简报仍可从 Actions artifacts 下载。

## 实现依据

- [Lilly 官方 RSS 入口](https://investor.lilly.com/rss-news-feeds)
- [Novo 官方公告档案](https://www.novonordisk.com/news-and-media/news-and-ir-materials.html)（适配其页面自身使用的公开接口，接口可能变更）
- [EMA 官方 RSS 说明](https://www.ema.europa.eu/en/news-events/rss-feeds)
- [Health Canada RSS 说明](https://recalls-rappels.canada.ca/en/rss-feeds)
- [Europe PMC Web Service](https://europepmc.org/RestfulWebService)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [FDA Foundayo 批准公告](https://www.fda.gov/news-events/press-announcements/fda-approves-first-new-molecular-entity-under-national-priority-voucher-program)（用于确认词表中 2026 年新增产品）
