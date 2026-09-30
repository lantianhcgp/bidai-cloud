---
name: bidai-cloud
description: "笔袋官方网盘（gaojiua.com/cloud）全功能 CLI：搜索试卷资源、浏览/转存/下载分享文件、管理自己网盘（上传/建目录/重命名/移动/复制/回收站）、分享创建与取消、PDF 预览。当用户要搜试卷、下载笔袋资料、管理网盘文件时触发。"
homepage: https://gaojiua.com/cloud/
metadata: { "requires": { "bins": ["python3"] } }
---

# 笔袋网盘 Skill（gaojiua.com）

把笔袋 App 官方网盘逆向成可编程 CLI。**全部端点实测过**，自测 40 项 39 PASS
（唯一"FAIL"是服务端 `share-create` 返回 500 但实际创建成功）。

## 一、前置：登录

```bash
CLI=~/.hermes/skills/bidai-cloud/scripts/bidai.py

python3 $CLI send-code <手机号>      # 发验证码短信（需要用户配合收码）
python3 $CLI login [手机号] <验证码>  # 登录，token 写入 ~/.bidai_token (600)
python3 $CLI whoami                  # 验证 + 查 token 有效期
```

- **token 有效期到 2036 年**（JWT exp 十年），正常情况登录一次即可，无需刷新。
- 手机号存在 `~/.bidai_config.json`(600)，下次登录可省略。
- 验证码 5 分钟有效，过期重发。

## 二、命令速查

```bash
# —— 找资源（匿名即可用）
python3 $CLI search 高考数学 --size 20      # 搜全站分享（试卷/资料）
python3 $CLI share-info <share_id>          # 分享详情（取 share_file_id）
python3 $CLI share-files <share_id> [--parent ID]   # 分享内文件列表，目录递归下钻

# —— 下载（核心链路）
python3 $CLI download-share <share_id> <file_id> [-o 路径] [--cleanup]
      # 转存到自己根目录 -> 拿签名直链 -> 下载 -> md5 校验
      # --cleanup: 下载后把转存副本丢进回收站（不污染网盘）

# —— 管理自己网盘
python3 $CLI ls [--parent ID] [--size 100]   # 列目录（根目录 parent=-1）
python3 $CLI tree [--depth 3]                # 递归树
python3 $CLI search-my 关键词                 # 搜自己空间
python3 $CLI recent / trash                  # 最近文件 / 回收站
python3 $CLI mkdir 名称 [--parent ID]
python3 $CLI rename <file_id> 新名
python3 $CLI mv <id...> --to <目录id>        # 移动
python3 $CLI cp <id...> --to <目录id>        # 复制
python3 $CLI rm <id...>                      # 进回收站
python3 $CLI rm <id...> --hard               # 永久删除（内部自动先入站）
python3 $CLI restore <id...>                 # 回收站恢复
python3 $CLI upload 本地文件 [--parent ID]   # 上传，<=100MB，自动秒传

# —— 拿直链 / 预览
python3 $CLI get-url 关键词                  # 签名直链（10 分钟内有效）
python3 $CLI download -k 关键词 [-o 路径]    # 下载自己空间的文件
python3 $CLI preview <file_url> --page 1 --size 4   # PDF 渲染页 JPG 地址

# —— 分享管理
python3 $CLI shares [--mine] [--size 100]    # 分享列表（--mine 只看自己）
python3 $CLI share-create <文件夹id> --title 标题 --tags 高中 数学
python3 $CLI share-update <share_id> --title 新标题 [--tags ...]
python3 $CLI share-delete <share_id...>
python3 $CLI star <share_id> / unstar / upvote
```

**输出**：默认 JSON；很多命令带 `--raw` 返回裸数组便于解析。
所有命令 `exit code 0=成功`，错误打到 stderr 且以 `error:` 开头。

## 三、关键机制（踩过的坑）

1. **根目录 id = `-1`**（不是 0）。`ls`/`mkdir`/`import` 的 parent 默认都是 -1。
2. **别人的分享文件不能直接下载**：`pre-download` 只认自己空间的文件
   （否则 400 "用户文件信息不匹配"）。必须先 `share/import` 转存，
   `download-share` 已把这步串好。
3. **COS 直链需要签名**：裸 `file_url` 下载返回 403 `invalid sign name`。
   签名直链从 `GET /api/cloud/file/pre-download/?file_id=&file_url=` 拿。
4. **上传**：`pre-create` 拿腾讯云临时凭证 -> COS q-sign 直传 -> `complete-upload`。
   同 md5 文件走秒传（回传一段 `check_bytes`）。单文件上限 100MB。
   q-sign 规范见 `_cos_put()` 注释（**StringToSign 末尾有个换行**，写错就 403）。
5. **`share/list` 不能传 `tags=[]`** —— 空数组会把结果全滤掉，不给 `--tag`
   就别带这个参数。
6. **`share-create` 服务端返回 500 但实际创建成功**（再建才报"禁止重复共享"）。
   判定成功以 `shares` 列表里能查到为准。
7. **`destroy`（永久删除）只对回收站内的项生效**，直接对根目录文件调用会
   返回 200 但什么都没删。`rm --hard` 已自动先入站。
8. **必需请求头**：`AppFingerprint: bidai`、`PlatformName: H5`，否则网关不认。
   CLI 已内置，自己写请求时别漏。
9. 分页参数统一 `page` + `page_size`；文件列表返回裸数组，靠长度判断有无下一页。

## 四、安全约定

- token 只存 `~/.bidai_token`（权限 600），**不写进 SKILL.md、不回显给聊天**。
- 报告/日志里出现手机号一律打码（只留后 4 位）。
- 删除、分享等破坏性操作只对自己新建的测试项做；动用户已有文件前先确认。

## 五、自测

```bash
python3 ~/.hermes/skills/bidai-cloud/scripts/selftest.py
```

覆盖：建目录、上传（正常+秒传）、改名、复制、移动、回收站、恢复、
永久删除、分享创建/详情/列表/取消、端到端下载（md5 校验），最后自动清理。
测试产物统一命名 `selftest/shraetest/probe`，跑完会把账号恢复原状。

## 六、未覆盖 / 已知限制

- 打印下单、地址、商城订单、充值等**电商链路**没做（有支付副作用，不碰）。
- admin 后台端点返回 403「没有权限」（需要平台员工账号）。
- `upvote`/`followUser` 等社交动作可用但没纳入自测（会产生他人可见的副作用）。
- 文件夹上传（整目录）未实现，只支持单文件上传。
