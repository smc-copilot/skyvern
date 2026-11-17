# PR-00 Fork 源码构建与隔离部署基线

文档状态：**APPROVED_FOR_PLAN**（用户 2026-11-16 明确批准将 PRD 状态从 REVIEW 改为 APPROVED_FOR_PLAN，并在 `smc-copilot/skyvern` 新分支推进 PR-00）。

本文件不是正式 Release Gate 通过声明。PRD 质量门仍要求「无 SPEC_SEMANTIC_GAP」才能声称完整 Plan/Release 通过；下列缺口已按范围阻断，未扩大成无关工作全局停工。

## 仓库身份（以最新明确目标为准）

| 项 | 值 |
| --- | --- |
| Fork | `smc-copilot/skyvern` |
| 上游 | `Skyvern-AI/skyvern` |
| 本云工作区 HEAD（创建分支前） | `716b256437bce90b3c83c52a8a401dff6779b33e` |
| `pyproject.toml` version | `1.0.57` |
| 建议分支名 | `feature/pr-00-enterprise-source-build` |
| 本 PR 实际分支 | `cursor/pr-00-enterprise-source-build-f090`（云代理分支命名约束） |
| 本地镜像 | `local/smc-copilot-skyvern-backend` / `local/smc-copilot-skyvern-ui` |
| Compose 项目名 | `skyvern-enterprise-pr00` |

PRD 原文中的 `loudon84/skyvern` 与 `local/loudon84-skyvern-*` 已被用户明确替换。不得把旧 Fork SHA `3ae1f0d5792482001ad119f529b1cd01a720956c` 当作本仓库现状。

## 上游基线（已核验，未静默替换）

| 项 | 值 |
| --- | --- |
| PRD 固定候选 SHA | `d04ca9c7fd9925216b3dcdc687203e9ee79de351` |
| 该 SHA 的 version | `1.0.57`（已读上游 `pyproject.toml`） |
| 当前上游 `main` | `e87b6910bd6ddaea6ac1e1d1e4beb455b24d93d6`（比固定 SHA 超前 13 个提交） |
| 本 Fork `main` 相对固定 SHA | 超前 8 个提交，固定 SHA 是祖先，不是落后 167 |

因此 `verify_upstream_baseline.py` 必须以 `UPSTREAM_BASELINE_DRIFT` 阻断 merge/rebase/SHA 替换。本 PR **没有** 把 HEAD 重置到固定 SHA，也没有合并上游 `main`。

n8n 仅作未来集成参考，本 PR 不改 `integrations/n8n`，不执行 `submodule update --remote`。

## SPEC_SEMANTIC_GAP（阻断对应部分，不猜测补全）

| ID | 缺口 | 阻断范围 |
| --- | --- | --- |
| GAP-EVIDENCE-PATH | REQ-STATE-001 写「用户指定的工作区外 Evidence 目录」，§24.1 又规定 `.enterprise-data/evidence/pr-00/` | 未另指定目录时，脚本默认写入 `.enterprise-data/evidence/pr-00/`（gitignore）。不把两种路径静默等同为同一权威源。 |
| GAP-DIRTY-BOUNDARY | Dirty 阻断同步（REQ-STATE / 冲突表）与 `build_images.sh --allow-dirty`（§13.6）并存 | 同步入口遇 Dirty → `WORKTREE_DIRTY`。构建默认真工作区；开发可用 `--allow-dirty`，Tag 必须带 `-dirty`，不得算 Release。 |
| GAP-DASHBOARD-ORG | A-SMOKE-002 是 `GET /` HTTP 200；Golden Consumer 要求「通过 UI 使用测试 Organization」，未定义操作步骤 | HTTP 200 可在 Smoke 中验证。浏览器内使用测试 Organization **BLOCKED**，不伪造页面操作。 |
| GAP-BUILD-STATE-MACHINE | §8.1 无 `BUILD_METADATA_CREATED`；REQ-BUILD-001 / §9.1 要求构建前 JSON（digest=null）再回填 | 按 §9.1 实现：先 metadata，再 build，再 backfill。不把「文件已生成」当成镜像已构建。 |
| GAP-PRODUCTION-IDENTITY | 用户生产实例、真实本地补丁、生产快照无法在本云环境核验 | 生产 Before/After 与本地补丁分类 **BLOCKED / UNKNOWN**。本云工作区不能代替用户现场验收。 |
| GAP-CI-EXISTING-JOBS | A-CI-002 `required_existing_ci_jobs` 未列举集合 | 静态确认 `ci.yml` 仍含 `pre-commit` / `pytest` / `test` / `fe-lint-build` / `pip-package-smoke`。GitHub 上这些 Job 的实际 success **待 PR CI 运行后才能记 VERIFIED**。 |
| GAP-VNC-ORACLE | REQ 规定 VNC Host 16080，A-COMPOSE-003 Oracle 未包含该端口 | Override 映射 16080。不把未写进 Oracle 的 VNC 检查标 PASS。 |
| GAP-WF-EXTRA | 仓库另有 `claude.yml` / `claude-code-review.yml` / `inactive-issues-and-prs.yml` / `zizmor.yml` 等写权限工作流，不在 PRD 的 7 个 Job 清单内 | 只给清单内 Job 加身份门禁。额外工作流记缺口，不擅自扩 Guard、不声称已全部无副作用。 |

## 不在本 PR 范围

- 不改 Browser Runtime / Workflow / CodeBlock / entrypoint
- 不采集网站、不建 Collector Registry
- 不发包、不推镜像、不触碰生产、不 `down -v`
- 不自动触发上游发布或跨仓库同步
- 不改造 n8n

## 命令（与脚本一致）

预检（只读）：

```bash
python3 scripts/enterprise/preflight.py
python3 scripts/enterprise/verify_upstream_baseline.py
python3 scripts/enterprise/check_upstream_workflow_guards.py
python3 scripts/enterprise/validate_compose.py
```

环境文件（已存在则不得覆盖）：

```bash
test -f .env.enterprise || { cp .env.example .env.enterprise; cat .env.enterprise.example >> .env.enterprise; }
test -f skyvern-frontend/.env.enterprise || cp skyvern-frontend/.env.enterprise.example skyvern-frontend/.env.enterprise
# 将 ENTERPRISE_POSTGRES_PASSWORD 换成随机字母数字，不要提交该文件
```

构建 / Smoke / 停止：

```bash
scripts/enterprise/build_images.sh          # 需要 Docker；Dirty 时加 --allow-dirty
scripts/enterprise/smoke_test.sh            # 构建失败不得启动
scripts/enterprise/stop_smoke.sh            # 停止容器与网络，保留 .enterprise-data/
```

测试端口：API `18000`，VNC `16080`，UI `18080`，Artifact `19090`。PostgreSQL 不映射宿主机 5432。

端口占用必须失败，脚本不会改端口。

本隔离 VM 若为嵌套 Docker，且 `net.bridge.bridge-nf-call-iptables=1`，compose 容器互访 TCP 可能超时。这是该 VM 的 Docker 网络现状，不是生产宿主配置。仅在本隔离 VM 上可设为 `0` 后再跑 Smoke；**不要**在用户生产机上改 sysctl。脚本不会自动改内核参数。

## 回滚

- 停止测试栈：`scripts/enterprise/stop_smoke.sh`
- 禁止 `docker compose down -v`、`docker volume prune`、`docker system prune`
- 禁止对生产 DB 做迁移或回滚
- Git 回滚用 `git revert` 或新修复提交，不用破坏性 reset

## Evidence

默认目录：`.enterprise-data/evidence/pr-00/`（不入库）。

`SKIPPED` / `BLOCKED` 不等于 `PASS`。没有 Docker 时，镜像 Digest、容器文件系统、API/UI HTTP、页面截图必须标 **BLOCKED**，不得用「文件已创建」代替运行验收。

本隔离 Cloud Agent VM（2026-11-17）已用官方 Docker CE 本地 daemon 完成 compose config、源码构建、Smoke、截图与 stop。那是本 VM 运行验收，不能代替用户生产现场。Golden Consumer 测试 Organization 步骤仍未定义，截图只证明 `GET /` 渲染了 Dashboard，不证明 Organization 操作。
