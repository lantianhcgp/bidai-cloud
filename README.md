# bidai-cloud — 笔袋网盘 CLI / Hermes Skill

把笔袋（gaojiua.com）官方网盘逆向成可编程的命令行工具，同时打包为 [Hermes Agent](https://hermes-agent.nousresearch.com) Skill。

搜试卷、看分享、转存、下载、上传、建目录、管理分享——原本只能在 App/网页里点的操作，现在一条命令就能做，方便写脚本、做自动化、接入 AI 工作流。

- **零第三方依赖**：纯 Python 标准库（`urllib` / `json` / `hmac`），有 `python3` 就能跑
- **32 个子命令**，覆盖找资源 → 转存 → 下载 → 网盘管理 → 分享全链路，端点全部实测
- **自测 18 步用例全绿**，覆盖建目录、上传（含秒传）、改名、复制、移动、回收站、恢复、永久删除、分享增删查、端到端下载（md5 校验），跑完自动把账号恢复原状
- **登录一次用十年**：token 是十年期 JWT（有效期至 2036 年），正常情况无需刷新

## 目录结构

```
bidai-cloud/
├── README.md              # 本文件
├── SKILL.md               # Hermes Skill 定义（触发条件 + 用法 + 踩坑清单）
├── scripts/
│   ├── bidai.py           # CLI 主程序（32 个子命令）
│   └── selftest.py        # 自测脚本（40 项，自清理）
└── docs/
    └── 验收报告.md         # 逆向与验收记录（端点探测、链路验证、修复清单）
```

## 安装

**作为 Hermes Skill**（装到技能目录即可被 Agent 自动加载）：

```bash
git clone https://github.com/lantianhcgp/bidai-cloud.git ~/.hermes/skills/bidai-cloud
```

**独立 CLI**（任何有 Python 3.8+ 的环境）：

```bash
git clone https://github.com/lantianhcgp/bidai-cloud.git
python3 bidai-cloud/scripts/bidai.py --help
```

## 快速开始

### 1. 登录（需收一条短信验证码）

```bash
CLI=scripts/bidai.py

python3 $CLI send-code <手机号>       # 发验证码短信
python3 $CLI login <手机号> <验证码>   # 登录，token 写入 ~/.bidai_token（权限 600）
python3 $CLI whoami                   # 校验 + 查 token 有效期
```

- 验证码 5 分钟有效，过期用 `send-code` 重发
- 手机号存 `~/.bidai_config.json`（600），下次 `login` 可省略
- `search` / `share-info` / `share-files` 等**找资源的命令匿名可用**，只有写操作需要登录

### 2. 找资源并下载

```bash
python3 $CLI search 高考数学 --size 20     # 搜全站分享
python3 $CLI share-info <share_id>         # 分享详情（拿 share_file_id）
python3 $CLI share-files <share_id>        # 分享内文件列表（--parent 下钻目录）
python3 $CLI download-share <share_id> <file_id> -o ./out.pdf
```

`download-share` 已把「转存到自己空间 → 拿签名直链 → 下载 → md5 校验」串成一步；加 `--cleanup` 会在下载后把转存副本丢进回收站，不污染网盘。

### 3. 管理自己的网盘

```bash
python3 $CLI ls                     # 列根目录（根目录 id 是 -1，不是 0）
python3 $CLI mkdir 高三数学
python3 $CLI upload ./讲义.pdf --parent <目录id>
python3 $CLI trash                  # 回收站
python3 $CLI rm <file_id>           # 进回收站（--hard 才是永久删除）
```

## 命令一览

| 分组 | 命令 |
| --- | --- |
| 登录账号 | `send-code` `login` `whoami` |
| 找资源（匿名可用） | `search` `share-info` `share-files` `import` `preview` |
| 下载 / 直链 | `get-url` `download` `download-share` |
| 自己网盘管理 | `ls` `search-my` `tree` `recent` `trash` `mkdir` `rename` `mv` `cp` `rm` `restore` `upload` |
| 分享管理 | `shares` `share-create` `share-update` `share-delete` `star` `unstar` `upvote` |
| 其他 | `quark-import`（转存夸克网盘链接） `shortlink`（生成短链） |

**输出约定**：默认 JSON，加 `--raw` 返回裸数组便于解析；`exit code 0` 表示成功，错误写 stderr 且以 `error:` 开头。逐条用法见 `python3 $CLI <命令> --help`。

## 逆向要点

网关 `https://api.gaojiua.com/release`，自研请求头 **`AppFingerprint: bidai` + `PlatformName: H5`**，缺一个网关就不认（CLI 已内置，自己写请求时别漏）。

| 能力 | 端点 |
| --- | --- |
| 发验证码 | `POST /api/user/token/code/`（`phone_number` + `system=H5`） |
| 登录 | `POST /api/user/token/`（`password` 字段填的是**验证码**） |
| 搜分享 | `GET /api/cloud/share/search/?keyword=&page=&page_size=` |
| 分享详情 / 文件列表 | `GET /api/cloud/share/info?share_id=` ／ `GET /api/cloud/share/file/list/?share_id=&parent_id=` |
| 转存 | `POST /api/cloud/share/import/`（根目录 `parent_id=-1`） |
| 拿签名直链 | `GET /api/cloud/file/pre-download/?file_id=&file_url=` → `signed_file_url` |
| 上传 | `POST .../pre-create`（腾讯云临时凭证）→ COS `PUT`（q-sign）→ `complete-upload` |
| 列表 / 分页 | 统一 `page` + `page_size`；列表接口响应在 `data.data` 或 `data.list`，文件列表是裸数组（靠长度判断下一页） |

COS 直传的 `StringToSign` 格式是 `put\n{uri}\n\n{k=v&k=v}\n`——**末尾有一个换行**，写错就是 403，细节见 `scripts/bidai.py` 里 `_cos_put()` 的注释。

## 踩过的坑

1. **根目录 id 是 `-1`**，不是 0；`ls` / `mkdir` / `import` 的 parent 默认都是 `-1`
2. **别人的分享文件不能直接下载**：`pre-download` 只认自己空间的文件（否则 400「用户文件信息不匹配」），必须先 `share/import` 转存——`download-share` 已串好
3. **裸 `file_url` 下载会 403** `invalid sign name`，签名直链要从 `pre-download` 拿
4. **`share/list` 不能传 `tags=[]`**：空数组会把结果全滤掉，不筛标签就别带这个参数
5. **`share-create` 服务端返回 500 但实际创建成功**——判定成功以 `shares` 列表里能查到为准
6. **`destroy`（永久删除）只对回收站内的项生效**：对根目录文件直接调用返回 200 但什么都没删，`rm --hard` 已自动先入站
7. **部分端点带尾斜杠**（`share/file/list/`、`share/import/`），不带会 404
8. **`share/info` 需要查询串参数**，走请求体会 404

## 自测

```bash
python3 scripts/selftest.py
```

18 步用例，覆盖主链路的正向与边界，测试产物统一用 `selftest/` 前缀命名，结束自动清理，账号恢复原状。最近一次实测 **18/18 PASS**，含端到端下载（679 KB 试卷，md5 校验一致）。`share-create` 服务端返回 500 但功能正常，脚本按「列表可查」判定，故记为 PASS。

## 安全约定

- token 只存 `~/.bidai_token`（权限 600），**不写进任何文档、不回显到聊天记录**
- 报告与日志中手机号一律打码（只留后 4 位）
- 删除、分享等破坏性操作只对自己新建的测试项执行；动已有文件前先确认
- 本仓库不含任何账号、token、cookie 或签名密钥

## 已知限制

- 打印下单、收货地址、商城订单、充值支付等**电商链路有意不做**（有真实资金副作用）
- admin 后台端点返回 403「没有权限」（需平台员工账号）
- `upvote` / `followUser` 等社交动作可用但未纳入自测（会对他人可见）
- 只支持单文件上传，整目录上传未实现（可用循环调用自己拼）

## 免责声明

本项目为个人学习与研究用途，逆向对象是公开可访问的 Web/H5 接口。使用本工具请遵守 gaojiua.com 的服务条款与相关法律法规，仅操作自己的账号与已获授权的内容；因使用本工具产生的任何后果由使用者自行承担。

---

如果你也在用 [Hermes Agent](https://hermes-agent.nousresearch.com)，把仓库 clone 到 `~/.hermes/skills/` 下即可作为 Skill 使用，Agent 会根据任务自动加载 `SKILL.md`。
