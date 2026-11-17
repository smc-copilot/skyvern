# PR-00 五项语义澄清（本轮澄清决策）

日期：2026-11-17  
范围：证据目录、Dirty 工作区、构建元数据顺序、VNC 健康标准、既有 CI Job 清单。  
不在本轮：上游 pin 漂移策略、生产身份事实、Dashboard 鉴权/Organization、额外 workflow 扩 Guard。

这些规则是保守、可机判的默认。它们关闭对应 `SPEC_SEMANTIC_GAP` 的**规则定义**，不把现场未取证的事实改写成 PASS，也不降低原 Required Acceptance。

## 1. 证据目录（原 GAP-EVIDENCE-PATH）

| 层 | 路径 | Git | 角色 |
| --- | --- | --- | --- |
| 未纳管原始运行证据 | `.enterprise-data/evidence/pr-00` | gitignore | **唯一权威**。日志、inspect、截图、preflight 原始 JSON。 |
| 可纳管脱敏摘要 | `docs/enterprise/pr00-cloud-agent-evidence.json` | 跟踪 | 引用一次运行的摘要。不能把 raw BLOCKED 改写成 PASS。 |

工作区外目录（preflight `--output-dir` 指向仓库外）只是**取证暂存**。导入：`python3 scripts/enterprise/evidence_policy.py --import-from <dir>`，复制进未纳管权威目录，且 `git_add_performed=false`。导入不创造第二权威源。

引用：raw 用相对路径 `.enterprise-data/evidence/pr-00/<file>`；摘要用 `docs/enterprise/pr00-cloud-agent-evidence.json#current`。摘要必须保留 `history[]`。

## 2. Dirty 工作区（原 GAP-DIRTY-BOUNDARY）

| 操作 | Dirty 是否允许 | 失败码 | Release |
| --- | --- | --- | --- |
| 只读诊断（preflight、默认 verify） | 允许，只记录 | 无 | 不适用 |
| 固定基线同步 / merge / rebase | 禁止 | `WORKTREE_DIRTY` | 不适用 |
| `build_images.sh --allow-dirty` | 允许，Tag 必须 `-dirty` | `DIRTY_RELEASE_BUILD` 若缺后缀 | **永不 PASS** |
| Release 门禁 | 禁止 | `DIRTY_RELEASE_BUILD` | Dirty 绝非 PASS |

脚本不得 `git stash` / `git reset --hard` / `git checkout --force`。`--allow-dirty` 是显式开发构建，不是清洁工作区的替代。

## 3. 构建元数据顺序（原 GAP-BUILD-STATE-MACHINE）

1. 构建前：`metadata_state=draft`，digest 均为 `null`，绑定当时 HEAD `source_commit`。  
2. 构建镜像（不 push）。  
3. 构建后：同一 SHA 上回填 digest，`metadata_state=acceptance`。  
4. Smoke / Release 只接受 `acceptance`。文件存在 ≠ 镜像已构建。  
5. `release_eligible=true` 仅当 clean **且** acceptance。Dirty acceptance 可存在，但不得 Release PASS。  
6. 一侧 digest 有值一侧为 null → `BUILD_METADATA_STATE_INVALID`。

## 4. VNC 健康标准（原 GAP-VNC-ORACLE）

实际协议：企业栈 Host `16080` → 容器 `6080` → `websockify` → `x11vnc` RFB `localhost:5900`（见 `entrypoint-skyvern.sh`）。

机判 oracle（`scripts/enterprise/vnc_oracle.py`）：

1. TCP 连接 `127.0.0.1:16080`（或配置端口），超时 5s。失败：`VNC_PORT_CLOSED` / `VNC_TIMEOUT`。  
2. HTTP WebSocket Upgrade，必须 **101**。HTTP **200**（含 Dashboard 或 HTML）→ `VNC_HTTP_NOT_WEBSOCKET`。  
3. 101 之后载荷必须含 `RFB ` 横幅。否则 `VNC_RFB_MISSING`。

容器 `running`、端口占用检查、UI `GET /` 200 **都不是** VNC PASS。

## 5. 既有 CI Job 清单（原 GAP-CI-EXISTING-JOBS）

权威清单：`scripts/enterprise/schemas/protected-ci-jobs.json`。键是 `workflow + job_id`，不是 GitHub check-run 显示名，也不是「16」这个历史计数。

`existing_protected`（必须仍存在于 `ci.yml`）：`pre-commit`、`pytest`、`test`、`fe-lint-build`、`pip-package-smoke`。  
矩阵轴不是额外 job_id。`test` 的 `if: always()` 是聚合器，期望 skip 不是它的语义。

Fork PR 上 `auto-merge` **预期 skip**（上游身份门禁）；skip ≠ 失败。  
`zizmor` 有 path filter；workflow YAML 未变时 run 缺失 ≠ 失败。  
job 删除 → `CI_JOB_REMOVED`；清单覆盖的 workflow 新增 job → `CI_JOB_ADDED`。  
不把 `f29a915fd` 的 16 项硬相等套到其他 SHA。`GAP-WF-EXTRA` 仍不扩 Guard。

## 与现场取证的分界

规则已定义。用户生产 Docker/Actions 是否启用、某 SHA 的 GitHub run 是否入队，仍是现场事实，不得伪造。
