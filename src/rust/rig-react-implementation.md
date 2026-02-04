# Rig ライブラリにおけるReAct実装の調査報告書

## エグゼクティブサマリー

Rigは、Rust製のLLMアプリケーションフレームワークであり、ReAct（Reason and Act）パターンを実装するための強力な機能を提供しています。本調査では、Rigの内部実装、アーキテクチャ、および実用的なexampleコードを詳細に分析しました。

## 1. ReActパターンとは

ReAct（Reasoning and Acting）は、LLMが以下のサイクルを繰り返すことで複雑なタスクを解決するパターンです：

1. **Reasoning（推論）**: タスクについて考え、次に何をすべきか判断
2. **Action（行動）**: ツールを呼び出して実際の操作を実行
3. **Observation（観察）**: ツール実行結果を観察
4. 必要に応じて1に戻る

## 2. Rigにおける実装方式

### 2.1 コア概念

Rigは以下の主要コンポーネントでReActパターンを実現しています：

#### Agent構造体
- LLMモデル、ツール、プロンプトを統合管理
- `AgentBuilder`パターンで構築
- `multi_turn()`メソッドでReActループを実現

#### Tool trait
```rust
pub trait Tool {
    const NAME: &'static str;
    type Error;
    type Args;
    type Output;

    async fn definition(&self, prompt: String) -> ToolDefinition;
    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error>;
}
```

### 2.2 Multi-Turn実装の仕組み

Rigの`multi_turn()`は以下のフローで動作します：

**ファイル**: `rig-core/src/agent/prompt_request/streaming.rs:111-394`

```rust
pub fn multi_turn(mut self, depth: usize) -> Self {
    self.max_depth = depth;
    self
}
```

**主要ロジック**:
1. **ループ開始**: `'outer: loop`で会話ターンを管理
2. **深さチェック**: `current_max_depth > self.max_depth + 1`で無限ループ防止
3. **LLM呼び出し**: `agent.stream_completion()`でストリーミング応答取得
4. **応答処理**:
   - `StreamedAssistantContent::Text`: テキスト応答 → ループ終了
   - `StreamedAssistantContent::ToolCall`: ツール呼び出し → 実行して継続
   - `StreamedAssistantContent::Reasoning`: 推論過程を記録
5. **履歴管理**: `chat_history`にツール呼び出しと結果を追加
6. **継続判定**: `did_call_tool`フラグでループ継続/終了を判断

### 2.3 ツール実行フロー

```rust
// ツール呼び出し検出
Ok(StreamedAssistantContent::ToolCall(tool_call)) => {
    // ツール実行
    let tool_result = agent.tools.call(
        &tool_call.function.name,
        tool_call.function.arguments.to_string()
    ).await?;

    // 結果をチャット履歴に追加
    chat_history.push(Message::User {
        content: OneOrMany::one(UserContent::tool_result(
            &id,
            OneOrMany::one(ToolResultContent::text(&tool_result)),
        )),
    });

    did_call_tool = true;
}
```

## 3. 実装Example分析

### 3.1 基本的なツール使用例

**ファイル**: `rig-core/examples/agent_with_tools.rs`

```rust
let calculator_agent = openai_client
    .agent(providers::openai::GPT_4O)
    .preamble("You are a calculator...")
    .tool(Adder)
    .tool(Subtract)
    .build();

let result = calculator_agent
    .prompt("Calculate 2 - 5")
    .await?;
```

**特徴**:
- シンプルな1ターンツール使用
- `.prompt().await`で自動的にツール実行
- LLMがツール選択と引数決定を担当

### 3.2 Multi-Turn ReAct Example

**ファイル**: `rig-core/examples/multi_turn_agent.rs`

```rust
let agent = anthropic_client
    .agent(anthropic::CLAUDE_3_5_SONNET)
    .preamble("You are an assistant...")
    .tool(Add)
    .tool(Subtract)
    .tool(Multiply)
    .tool(Divide)
    .build();

let result = agent
    .prompt("Calculate (3 + 5) / 9 = ?")
    .multi_turn(20)  // 最大20ターン
    .await?;
```

**動作フロー**:
1. プロンプト受信: `"Calculate (3 + 5) / 9 = ?"`
2. LLMが推論: 「まず3 + 5を計算する必要がある」
3. Tool呼び出し: `Add { x: 3, y: 5 }` → 結果: `8`
4. LLMが推論: 「次に8 / 9を計算」
5. Tool呼び出し: `Divide { x: 8, y: 9 }` → 結果: `0`（整数除算）
6. 最終応答: 「結果は0です（整数除算のため）」

### 3.3 Reasoning Loop Example

**ファイル**: `rig-core/examples/reasoning_loop.rs`

```rust
struct ReasoningAgent<M: CompletionModel> {
    chain_of_thought_extractor: Extractor<M, ChainOfThoughtSteps>,
    executor: Agent<M>,
}

impl<M: CompletionModel> Prompt for ReasoningAgent<M> {
    async fn prompt(&self, prompt: impl Into<Message>) -> Result<String, PromptError> {
        // 1. プロンプトから推論ステップを抽出
        let extracted = self
            .chain_of_thought_extractor
            .extract(prompt)
            .await?;

        // 2. 各ステップを文字列化
        let mut reasoning_prompt = String::new();
        for (i, step) in extracted.steps.iter().enumerate() {
            reasoning_prompt.push_str(&format!("Step {}: {}\n", i + 1, step));
        }

        // 3. Executorエージェントで実行（multi_turn使用）
        let response = self
            .executor
            .prompt(reasoning_prompt.as_str())
            .with_history(&mut chat_history)
            .multi_turn(20)
            .await?;

        Ok(response)
    }
}
```

**特徴**:
- **2段階アーキテクチャ**: Extractor + Executor
- **Chain-of-Thought抽出**: タスクを明示的なステップに分解
- **Structured Reasoning**: `ChainOfThoughtSteps`構造体で推論を構造化

**使用例**:
```rust
let agent = ReasoningAgent {
    chain_of_thought_extractor: anthropic_client
        .extractor(anthropic::CLAUDE_3_5_SONNET)
        .preamble("Extract reasoning steps from the prompt")
        .build(),

    executor: anthropic_client
        .agent(anthropic::CLAUDE_3_5_SONNET)
        .tool(Add)
        .tool(Subtract)
        .tool(Multiply)
        .tool(Divide)
        .build(),
};

let result = agent
    .prompt("Calculate ((15 + 25) * (100 - 50)) / (200 / (10 + 10))")
    .await?;
```

## 4. アーキテクチャ詳細

### 4.1 レイヤー構造

```
┌─────────────────────────────────────┐
│   Application Layer                 │
│   (ReasoningAgent, Custom Agents)   │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   Agent Layer                       │
│   - AgentBuilder                    │
│   - PromptRequest                   │
│   - multi_turn() logic              │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   Tool Layer                        │
│   - Tool trait                      │
│   - ToolDefinition                  │
│   - Dynamic tool calling            │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   Completion Layer                  │
│   - CompletionModel trait           │
│   - Provider implementations        │
│   - Streaming support               │
└─────────────────────────────────────┘
```

### 4.2 メッセージフロー

```
User Prompt
    ↓
┌───────────────────────────────────┐
│ Agent.prompt().multi_turn(depth)  │
└───────────────┬───────────────────┘
                ↓
    ┌───────────────────────┐
    │  Start Loop (depth=0) │
    └───────┬───────────────┘
            ↓
    ┌───────────────────────────┐
    │ LLM Streaming Completion  │
    └───────┬───────────────────┘
            ↓
    ┌───────────────────────┐
    │ Response Type?        │
    └───┬─────────┬─────────┘
        │         │
    Text│         │ToolCall
        │         │
        ↓         ↓
    [Return]  ┌────────────────┐
              │ Execute Tool   │
              └────┬───────────┘
                   ↓
              ┌────────────────────┐
              │ Add to chat_history│
              └────┬───────────────┘
                   ↓
              ┌────────────────┐
              │ depth++        │
              └────┬───────────┘
                   ↓
              [Loop back if depth < max]
```

### 4.3 チャット履歴の構造

```rust
chat_history: Vec<Message>

// Example:
[
  Message::User { content: "Calculate (3 + 5) / 9" },
  Message::Assistant { content: ToolCall(Add { x: 3, y: 5 }) },
  Message::User { content: ToolResult { id: "call_1", result: "8" } },
  Message::Assistant { content: ToolCall(Divide { x: 8, y: 9 }) },
  Message::User { content: ToolResult { id: "call_2", result: "0" } },
  Message::Assistant { content: Text("The result is 0") },
]
```

## 5. 主要な設計パターン

### 5.1 Builder Pattern
```rust
let agent = client
    .agent(MODEL)
    .preamble("system prompt")
    .tool(Tool1)
    .tool(Tool2)
    .max_tokens(1024)
    .build();
```

### 5.2 Trait-based Polymorphism
- `CompletionModel` trait: 複数プロバイダー対応
- `Tool` trait: 任意のツール実装可能
- `Prompt` trait: カスタムプロンプト処理

### 5.3 Streaming-first Design
- すべてのLLM呼び出しはストリーミング対応
- `async_stream` crateで実装
- Token-by-tokenまたはChunk-by-chunkで処理

### 5.4 Type-safe Tool Arguments
```rust
#[derive(Deserialize)]
struct OperationArgs {
    x: i32,
    y: i32,
}

impl Tool for Add {
    type Args = OperationArgs;
    // コンパイル時に型安全性を保証
}
```

## 6. ReActパターンの利点と制約

### 利点
1. **透明性**: ツール呼び出しと推論過程が明確
2. **制御性**: `max_depth`で無限ループを防止
3. **拡張性**: 新しいツールを簡単に追加可能
4. **型安全**: Rustの型システムで安全性を保証

### 制約
1. **トークン消費**: 各ターンでLLM呼び出しが発生
2. **レイテンシ**: 複数ターンで遅延が累積
3. **コスト**: API呼び出し回数に比例してコスト増加
4. **エラー伝播**: ツールエラーが会話を中断する可能性

## 7. 実装時のベストプラクティス

### 7.1 適切なmax_depth設定
```rust
// シンプルなタスク: 3-5ターン
.multi_turn(5)

// 複雑なタスク: 10-20ターン
.multi_turn(20)

// 自律的なタスク: 50-100ターン
.multi_turn(100)
```

### 7.2 明確なツール定義
```rust
async fn definition(&self, _prompt: String) -> ToolDefinition {
    json!({
        "name": "add",
        "description": "Add x and y together",  // 明確な説明
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "The first number to add"  // 各パラメータも説明
                },
                // ...
            }
        }
    })
}
```

### 7.3 System Promptの工夫
```rust
.preamble("
    You are an assistant here to help with arithmetic operations.
    IMPORTANT:
    1. Always use the provided tools - never calculate manually
    2. Call tools one at a time
    3. After getting results, explain them to the user
")
```

### 7.4 エラーハンドリング
```rust
impl Tool for MyTool {
    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        // バリデーション
        if args.x == 0 {
            return Err(MyError::InvalidInput);
        }

        // 実行
        Ok(perform_operation(args))
    }
}
```

## 8. 他のフレームワークとの比較

### LangChain (Python) との比較

**類似点**:
- Tool/Agent抽象化
- Multi-turn conversation support
- Streaming対応

**Rigの優位点**:
- 型安全性（Rustの型システム）
- パフォーマンス（ネイティブコンパイル）
- メモリ安全性

**LangChainの優位点**:
- エコシステムの充実
- 豊富なintegration
- 学習リソースの多さ

## 9. 結論

RigライブラリのReAct実装は、以下の特徴を持つ：

1. **`multi_turn()`メソッド**による直感的なReActループ実装
2. **Streaming-first**アーキテクチャでリアルタイム性を確保
3. **Trait-based**設計により高い拡張性
4. **型安全**なツール定義とエラーハンドリング
5. **Reasoning Loop Example**による高度なChain-of-Thought実装

RigはRustエコシステムにおいて、型安全で高性能なReActパターン実装を提供する優れた選択肢である。

## 参考ファイル

- `rig-core/src/agent/prompt_request/streaming.rs` (111-394行目): Multi-turnロジック
- `rig-core/examples/reasoning_loop.rs`: Reasoning Agent実装
- `rig-core/examples/multi_turn_agent.rs`: 基本的なMulti-turn使用例
- `rig-core/examples/agent_with_tools.rs`: シンプルなツール使用例
- `rig-core/src/agent/tool.rs`: Tool trait定義


---

## Metadata

Last Updated: 2025-10-10T12:07:40.921Z
Goal: rigライブラリのReAct（Reason and Act）実装の仕組み、アーキテクチャ、実装例を理解する
Query: ReAct agent reasoning acting loop implementation
Summary: RigライブラリにおけるReActパターン実装を詳細に調査。multi_turn()メソッドによるループ実装、Tool traitベースの型安全なツールシステム、Streaming-firstアーキテクチャ、Reasoning Loopによる高度なChain-of-Thought実装などを分析。実用的なexampleコードと実装パターンも含む包括的な報告書。
Tags: rig, react, agent, rust, llm, tool-calling, multi-turn, chain-of-thought
CreatedBy: agent
CreatedAt: 2025-10-10T12:07:40.921Z
