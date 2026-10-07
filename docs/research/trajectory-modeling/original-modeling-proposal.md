---
added: 2026-10-01
---

# Agent 历史轨迹的个性化建模与瓶颈分析方案

> 历史来源：本页为2026-10-01 的研究／建模提案，2026-10-07 从团队 Vault 迁入。原位置：`项目/Orbit/Agent 历史轨迹的个性化建模与瓶颈分析方案.md`。正文与原有日期、结论保留，仅整理导航和空白；私人会话定位不公开。本文中的“当前”、TODO、测试数量和执行命令仅对原文基线成立，本次没有重新验证，也不自动形成任务或授权。现行入口：[源码文档](<../../modules/analytics/README.md>)。

## 1. 建模目标

对于一个用户与 Agent 的长期交互历史，将其划分为若干 trajectory：

$$
\tau_i=
\{(s_{i,n},a_{i,n},s_{i,n+1})\}_{n=0}^{N_i-1}.
$$

其中：

- $s_n$：第 $n$ 个离散时刻的工作状态；
- $a_n$：用户在当前状态下给 Agent 的输入；
- $q(s_{n+1}|s_n,a_n)$：Agent 实际产生下一状态的条件分布；
- $p(s_{n+1}|s_n,a_n)$：用户希望获得的下一状态分布。

个性化 Agent 的目标定义为

$$
\min_q
\mathbb E_{(s,a)\sim\mathcal D_u}
\left[
L\big(
p_u(\cdot|s,a),
q(\cdot|s,a)
\big)
\right].
$$

这里 $p_u$ 带有用户下标，因为不同用户面对完全相同的任务，其期望工作方式也可能不同。

例如，有人希望：

$$
\text{问题}\rightarrow\text{Agent直接修改代码}
$$

而另一个用户希望：

$$
\text{问题}\rightarrow\text{解释原因}
\rightarrow\text{提出方案}
\rightarrow\text{等待确认}.
$$

两种行为本身都正确，区别属于 personalization 而不是能力差异。

---

## 2. 状态 $s_n$：当前到底发生了什么

一个重要原则是：

> $s_n$ 不应该只是聊天文本，而应尽可能成为预测下一步行为的近似 Markov sufficient state。

定义

$$
s_n=
(
s_n^{task},
s_n^{artifact},
s_n^{progress},
s_n^{execution},
s_n^{interaction},
s_n^{history}
).
$$

### 2.1 Task state：任务本身

描述“现在正在解决什么”。

主要 features：

| Feature | 示例 |
|---|---|
| task type | debug / coding / refactor / search / write / explain |
| domain | frontend / ML / numerical computing / DevOps |
| semantic embedding | 当前任务文本 embedding |
| complexity | 简单修改 / 多文件 / architecture |
| scope | file / module / repo / multi-repo |
| ambiguity | requirement 是否明确 |
| novelty | 与过去任务相似程度 |

其中可以用

$$
e_n^{task}
=
\operatorname{Embedding}(\text{task description})
$$

作为高维语义表示。

---

### 2.2 Artifact state：Agent 正在操作什么

例如 Codex 中：

- repository；
- 当前 branch；
- 当前文件；
- 修改文件数量；
- diff size；
- programming language；
- dependency；
- test suite；
- git status。

形成

$$
s_n^{artifact}
=
(\text{repo},\text{files},\text{diff},\text{dependencies},\ldots).
$$

这部分尽量由程序直接解析，不用 LLM。

---

### 2.3 Progress state：任务做到哪里

例如：

$$
s_n^{progress}
=
(
\text{completion},
\text{correctness},
\text{remaining problems},
\text{uncertainty}
).
$$

可以包含：

- 是否已有 solution；
- test passed ratio；
- 当前 error 数量；
- unresolved TODO；
- 是否出现重复错误；
- 当前阶段：
  - understand
  - plan
  - implement
  - verify
  - repair
  - finish

特别重要，因为：

> 相同 prompt 在“刚开始”和“已经失败三次”的语义完全不同。

---

### 2.4 Execution state：Agent 实际执行情况

记录：

- tool sequence；
- shell command；
- test；
- search；
- git；
- browser；
- MCP / skill；
- command success/failure；
- latency；
- token；
- CPU / API cost。

例如：

$$
\text{read}
\rightarrow
\text{edit}
\rightarrow
\text{test}
\rightarrow
\text{error}
$$

本身就是一个非常重要的状态。

---

### 2.5 Interaction state：人与 Agent 的关系状态

包括：

- 当前已经进行多少 turns；
- 用户纠正次数；
- interrupt 次数；
- retry 次数；
- Agent 是否刚刚失败；
- 用户是否接受此前方案；
- 用户是否频繁要求解释；
- 用户是否允许自主执行。

例如定义：

$$
F_n=
\frac{
N_{\rm correction}
+
N_{\rm retry}
+
N_{\rm failure}
}{
n+1
}
$$

作为当前 interaction friction。

---

### 2.6 History state

纯粹的 $s_n$ 很难满足 Markov 性，因此需要一个 history representation：

$$
h_n
=
f_\psi(
s_0,a_0,\ldots,s_n
).
$$

实际可以使用：

- rolling statistics；
- Transformer/RNN embedding；
- 最近 $K$ 个 events；
- trajectory summary。

最终实际模型输入建议写成：

$$
\boxed{
\tilde s_n=(s_n,h_n)
}
$$

而不是假设原始 $s_n$ 真的是 Markov state。

---

## 3. 用户输入 $a_n$：用户现在希望 Agent 做什么

不要简单把 prompt embedding 当作 $a_n$。

定义：

$$
a_n=
(
a_n^{intent},
a_n^{semantic},
a_n^{constraint},
a_n^{control},
a_n^{feedback},
a_n^{verification}
).
$$

### 3.1 Intent

分类例如：

$$
\{
Ask,\ Explain,\ Plan,\ Execute,\ Modify,\ Debug,\ Verify,\ Search
\}.
$$

一个 prompt 可以 multi-label。

---

### 3.2 Semantic content

直接使用 embedding：

$$
e_n^a
=
\operatorname{Embedding}(\text{user message}).
$$

用于判断：

- 当前任务；
- 与过去任务相似度；
- requirement drift；
- topic change。

---

### 3.3 Constraints

从文本抽取：

- “不要修改 X”
- “只修改这个函数”
- “不要联网”
- “直接完成”
- “先解释”
- “保持 API 不变”
- “需要 test”

这些 constraint 对 $p$ 尤其关键。

---

### 3.4 Control preference

例如：

- ask-before-act；
- direct execution；
- step-by-step；
- only suggestion；
- high autonomy。

这是后来 Personality 中 Autonomy 轴的重要 observation。

---

### 3.5 Feedback

这是推断 $p$ 最重要的信息之一：

$$
a_n^{feedback}
\in
\{
accept,
correct,
reject,
clarify,
retry,
expand
\}.
$$

例如：

> “不是，我的意思是……”

是非常强的 negative preference signal。

而：

> “对，就这样，继续。”

则是非常强的 positive preference signal。

---

## 4. Agent 转移模型 $q$

定义

$$
q_\phi(s_{n+1}|s_n,a_n).
$$

其含义是：

> 在当前环境和用户要求下，这个 Agent 实际倾向于把系统带到什么状态。

实际上直接预测整个 $s_{n+1}$ 太困难。

建议改为预测：

$$
\Delta s_n=s_{n+1}-s_n.
$$

并且 factorize：

$$
q(\Delta s|s,a)
=
q_{\rm action}
q_{\rm outcome}
q_{\rm cost}
q_{\rm interaction}.
$$

例如分别预测：

### Action

下一步会：

$$
read/edit/test/search/explain/ask/commit
$$

### Outcome

$$
success/error/partial
$$

### Cost

$$
latency,\ tokens,\ toolcalls
$$

### Interaction consequence

用户下一步：

$$
accept/correct/retry/abandon.
$$

这比直接预测一个巨大 state vector 更实际。

---

## 5. 用户理想转移模型 $p$

这是整个系统最核心、也是最容易建模错误的部分。

用户实际上不会直接告诉系统：

$$
p(s_{n+1}|s_n,a_n).
$$

因此 $p$ 是一个 latent distribution。

需要从之后发生的行为反推。

---

### 5.1 Positive evidence

如果 Agent 到达 $s_{n+1}$ 后用户：

- 接受结果；
- 不再修改；
- commit；
- 继续进入下一任务；
- 明确表示认可；

那么：

$$
p(s_{n+1}|s_n,a_n)
$$

应该较高。

---

### 5.2 Negative evidence

如果随后发生：

- retry；
- correction；
- rollback；
- manual rewrite；
- “不是这个意思”；
- 同问题重新提问；
- abandon；

则说明：

$$
p(s_{n+1}|s_n,a_n)
$$

应该较低。

因此定义 observation：

$$
r_n=
(
accept,
correction,
rollback,
retry,
manual\_edit,
abandon,\ldots
).
$$

然后建模：

$$
p_\theta(s'|s,a)
\propto
\exp
U_\theta(s,a,s').
$$

这里 $U_\theta$ 可以理解为：

> 用户对某一个 next state 的 latent utility。

---

## 6. Personalized loss

如果 $p$ 已知，那么最自然的是：

$$
L(p,q)=D_{\mathrm{KL}}(p\|q).
$$

等价于：

$$
L
=
-\mathbb E_{s'\sim p}
\log q(s'|s,a)
$$

因为：

$$
H(p,q)
=
H(p)+D_{\mathrm{KL}}(p\|q).
$$

当 $p$ 固定时，最小化 cross entropy 即最小化 KL divergence。

因此可以把 personalization 理解为：

$$
\boxed{
\begin{gathered}
\text{让 Agent 实际产生的 transition distribution}\ q\\
\text{逐渐逼近用户 preferred transition}\ p
\end{gathered}
}
$$

实际建议使用：

$$
L=
\lambda_1L_{\rm action}
+\lambda_2L_{\rm outcome}
+\lambda_3L_{\rm interaction}
+\lambda_4L_{\rm cost}.
$$

因为不同 state dimensions 的数据类型不同：

- categorical → cross entropy；
- continuous → MSE / Gaussian likelihood；
- semantic state → cosine / Wasserstein；
- sequence → sequence likelihood。

而不是强行对整个 state 使用一个 KL。

---

## 7. 不同 trajectory 如何交互

这是模型能否真正形成“用户画像”的关键。

如果每个 trajectory 独立分析，只能得到 session analytics，而不能得到 personalization。

引入三个 latent variables：

$$
z_u,\qquad
z_{\rm project},\qquad
z_{\rm task}.
$$

其中：

- $z_u$：用户长期稳定偏好；
- $z_{\rm project}$：某个项目特有工作方式；
- $z_{\rm task}$：当前任务的局部性质。

于是：

$$
p(
s'|s,a
)
=
p(
s'|s,a,
z_u,z_{\rm project},z_{\rm task}
).
$$

---

### 7.1 User-level information sharing

所有 trajectory：

$$
\tau_1,\tau_2,\ldots,\tau_M
$$

共同更新用户 embedding：

$$
z_u=
F(\tau_1,\ldots,\tau_M).
$$

例如：

> 用户在十几个不同项目中都频繁要求 test 后再提交。

那么这是 user preference，而不是某个 project 特征。

---

### 7.2 Similar trajectory sharing

并不是所有 trajectory 应该等权互相影响。

定义 trajectory embedding：

$$
e_i=E(\tau_i).
$$

然后定义 similarity：

$$
K_{ij}
=
\exp
\left(
-\frac{
\|e_i-e_j\|^2
}{\sigma^2}
\right).
$$

对于当前 trajectory $i$，过去 trajectory $j$ 的贡献按

$$
w_{ij}
=
\frac{K_{ij}}
{\sum_kK_{ik}}
$$

加权。

这样：

> debug Python 项目

会主要参考过去的 debug / Python / 类似 tool workflow，而不是一个完全无关的写文档任务。

---

### 7.3 Relation Graph

进一步可以构造 trajectory graph。

节点：

$$
\tau_i
$$

边由以下关系产生：

- same repo；
- same task type；
- semantic similarity；
- same error；
- same tool sequence；
- temporal proximity；
- same outcome pattern。

从而形成：

$$
G=(V,E).
$$

之后可以做：

- graph clustering；
- label propagation；
- GNN；
- neighborhood statistics。

MVP 阶段实际上不需要 GNN，简单 similarity graph 已经足够。

---

## 8. 时间效应：用户偏好不是永远不变

应该允许：

$$
z_u(t)
$$

缓慢变化。

例如采用 exponential forgetting：

$$
w(\Delta t)
=
e^{-\lambda\Delta t}.
$$

最近的 trajectory 权重更高。

于是：

$$
z_u(t)
=
\frac{
\sum_i
e^{-\lambda(t-t_i)}e_i
}{
\sum_i
e^{-\lambda(t-t_i)}
}.
$$

这样可以识别：

> 用户以前倾向于自己控制 Agent，但最近越来越习惯 delegate。

这实际上就是很适合 Lifeline 产品展示的东西。

---

## 9. Bottleneck 的数学定义

对于每个 transition 定义：

$$
B_n
=
D(
p(\cdot|s_n,a_n),
q(\cdot|s_n,a_n)
).
$$

$B_n$ 大意味着：

> 用户期望和 Agent 实际行为严重不匹配。

然后按照不同 feature 聚合：

$$
B_{\rm task},
B_{\rm tool},
B_{\rm project},
B_{\rm stage}.
$$

于是可以得到：

> 你的总体 coding personalization 已经很好，但在 debugging 阶段 $D(p,q)$ 显著升高。

进一步：

> 其中最大的 mismatch 来自 Agent 在 test failure 后直接继续修改代码，而你更倾向先定位 error source。

这才是真正有价值的 bottleneck diagnosis。

---

## 10. 从 Bottleneck 到 Skill Recommendation

假设安装某一个 skill $k$ 后 Agent transition 变成：

$$
q^{(k)}.
$$

则定义 skill gain：

$$
G_k
=
L(p,q)
-
L(p,q^{(k)})
-
\lambda C_k.
$$

其中 $C_k$ 是：

- additional latency；
- token；
- setup cost；
- interaction cost。

因此推荐问题成为：

$$
k^*
=
\arg\max_k G_k.
$$

即：

> 推荐最能够缩小 $p-q$ gap 的 skill，而不是推荐“大家都喜欢的 skill”。

这就是 personalization recommendation 的统一数学定义。

---

## 11. 十六人格只是 $z_u$ 的低维可解释投影

内部不要真的只保留四个 binary variables。

内部学习：

$$
z_u\in\mathbb R^d,
\qquad d\approx16\sim128.
$$

然后为了展示，将它投影成四个轴：

$$
Rz_u=
(x_A,x_P,x_V,x_O).
$$

分别表示：

### Autonomy

$$
Controller
\leftrightarrow
Delegator
$$

### Workflow

$$
Planner
\leftrightarrow
Explorer
$$

### Verification

$$
Validator
\leftrightarrow
Accelerator
$$

### Scope

$$
Specialist
\leftrightarrow
Orchestrator.
$$

最后通过正负号映射为：

$$
2^4=16
$$

种 Personality。

因此正确关系应该是：

$$
\boxed{
\begin{gathered}
Raw\ trajectories\rightarrow latent\ preference\ z_u\\
\rightarrow16D/64D\ internal\ profile\\
\rightarrow4D\ interpretable\ projection\rightarrow16\ personalities
\end{gathered}
}
$$

而不能反过来为了凑十六人格，直接用四个统计指标描述用户。

---

## 12. 推荐的实际数据 Pipeline

第一阶段：

$$
\text{Codex raw logs}
$$

↓

### Event normalization

统一成为：

```text
timestamp
trajectory_id
state
user_action
agent_action
tool
result
latency
token
feedback
```

↓

### Feature extraction

**程序完成：**

- time
- tool
- git diff
- error
- test
- retry
- latency
- file
- cost

**Embedding / LLM 完成：**

- task intent
- requirement
- correction semantics
- task similarity
- autonomy preference
- satisfaction signal

↓

### Storage

推荐：

```text
JSONL
  ↓
Parquet
  ↓
DuckDB
```

Python：

```text
Polars / Pandas
```

↓

### Representation

```text
Embedding
+ trajectory statistics
+ process features
```

↓

### Analysis

```text
HDBSCAN / clustering
UMAP
process mining
Markov transition
time-series
```

↓

### Preference model

$$
p_\theta
$$

↓

### Agent behavior model

$$
q_\phi
$$

↓

### Gap analysis

$$
D(p,q)
$$

↓

### Personality
### Bottleneck
### Skill recommendation

---

## 13. 最终模型的核心结构

整个项目实际上可以浓缩成：

$$
\boxed{
\begin{aligned}
&s_n
&&=\text{Current working state},\\
&a_n
&&=\text{User intention},\\
&q_\phi(s'|s_n,a_n)
&&=\text{Agent behavior},\\
&p_\theta(s'|s_n,a_n,z_u)
&&=\text{User preference},\\
&z_u
&&=\text{cross-trajectory user representation}.
\end{aligned}}
$$

目标：

$$
\boxed{
\min
\mathbb E
D(
p_\theta(\cdot|s,a,z_u)
\|
q_\phi(\cdot|s,a)
)
}
$$

而产品的三个输出分别是：

$$
z_u
\rightarrow
\text{Personality},
$$

$$
D(p,q)
\rightarrow
\text{Bottleneck},
$$

$$
\arg\min_k D(p,q^{(k)})
\rightarrow
\text{Recommendation}.
$$

这三个功能因此不是三个独立 feature，而是同一个数学模型的三个不同投影。
