# Rust製テンプレートコンパイラの設計比較 — Vue (Vize) vs Angular (OXC Angular Compiler)

## 概要

Rust で書かれた2つのフロントエンドテンプレートコンパイラ（Vue 用の Vize と Angular 用の OXC Angular Compiler）のコードベースを探索し、コンパイルパイプラインの設計思想・中間表現・最適化戦略・出力コードの根本的な違いを理解した。

## 背景・きっかけ

voidzero-dev/oxc-angular-compiler と ubugeeei/vize のコードベースを探索し、両者の内部構造を詳細に調査した。どちらも OXC エコシステムを活用した Rust 製コンパイラだが、ターゲットフレームワーク（Angular vs Vue）の設計思想の違いがコンパイラ設計に大きく反映されている。

## 学んだこと

### 1. コンパイルパイプラインの構造比較

両者とも多段パイプラインだが、中間表現の粒度とフェーズ数が大きく異なる。

```
Vue (Vize):     HTML Parse → AST → ディレクティブ変換 → Hoisting/PatchFlag → render関数
Angular (OXC):  HTML Parse → R3 AST → IR Ops → 67フェーズ最適化 → Reify → JS出力
```

Angular は CreateOp/UpdateOp のダブルリンクリストという専用 IR を持ち、67個の独立した変換フェーズを順次適用する。Vue は AST ノードを直接変換する方式で、ディレクティブごとに変換ロジックが分離されている。

### 2. Angular の IR 設計：Operation リストとダブルリンクリスト

Angular コンパイラの核心は、テンプレートの各操作を `CreateOp`（初期化時）と `UpdateOp`（変更検出時）に分離する IR 設計にある。

`crates/oxc_angular_compiler/src/ir/ops.rs`:

```rust
// Create Operations - 初期化時に1回実行される操作
pub enum CreateOp<'a> {
    ElementStart(ElementStartOp<'a>),
    Element(ElementOp<'a>),
    ElementEnd(ElementEndOp<'a>),
    Template(TemplateOp<'a>),
    Text(TextOp<'a>),
    Listener(ListenerOp<'a>),
    Conditional(ConditionalOp<'a>),
    RepeaterCreate(RepeaterCreateOp<'a>),
    Defer(DeferOp<'a>),
    Pipe(PipeOp<'a>),
    I18nStart(I18nStartOp<'a>),
    // ... 計30以上のバリアント
}

// Update Operations - 変更検出サイクルごとに実行
pub enum UpdateOp<'a> {
    InterpolateText(InterpolateTextOp<'a>),
    Property(PropertyOp<'a>),
    StyleProp(StylePropOp<'a>),
    ClassProp(ClassPropOp<'a>),
    Attribute(AttributeOp<'a>),
    Repeater(RepeaterOp<'a>),
    Conditional(ConditionalUpdateOp<'a>),
    // ... 計20以上のバリアント
}
```

各 Op はダブルリンクリスト上のノードとして管理される。`prev`/`next` ポインタを持ち、フェーズ中の O(1) 挿入/削除を可能にしている。

`crates/oxc_angular_compiler/src/ir/list.rs`:

```rust
pub struct OpList<'a, T: Op> {
    head: Option<NonNull<T>>,
    tail: Option<NonNull<T>>,
    len: usize,
    allocator: &'a Allocator,
}

// カーソルによる走査と同時変更
pub struct OpListCursor<'b, 'a, T: Op> {
    list: &'b mut OpList<'a, T>,
    current: Option<NonNull<T>>,
}

impl<'b, 'a, T: Op> OpListCursor<'b, 'a, T> {
    pub fn move_next(&mut self) -> bool { /* ... */ }
    pub fn insert_before(&mut self, op: T) { /* ... */ }
    pub fn remove_current(&mut self) { /* ... */ }
    pub fn replace_current(&mut self, op: T) { /* ... */ }
}
```

このカーソルパターンにより、67フェーズのそれぞれがリストを走査しながら安全に操作を挿入・削除・置換できる。Vue にはこの概念がなく、AST ノードを直接変更する。

### 3. Vue の AST 設計：VNodeCall とコードジェンノードの二層構造

Vue は IR を持たず、AST ノードに `codegen_node` フィールドを付与して変換結果を保持する設計。

`crates/vize_relief/src/ast.rs`:

```rust
pub struct ElementNode<'a> {
    pub ns: Namespace,
    pub tag: String,
    pub tag_type: ElementType,
    pub props: Vec<'a, PropNode<'a>>,
    pub children: Vec<'a, TemplateChildNode<'a>>,
    // 変換後にセットされるコードジェン情報
    pub codegen_node: Option<ElementCodegenNode<'a>>,
    pub hoisted_props_index: Option<usize>,
}

// VNodeCall - Vue のコードジェンの核心
pub struct VNodeCall<'a> {
    pub tag: VNodeTag<'a>,
    pub props: Option<PropsExpression<'a>>,
    pub children: Option<VNodeChildren<'a>>,
    pub patch_flag: Option<PatchFlags>,       // 最適化ヒント
    pub dynamic_props: Option<DynamicProps<'a>>,
    pub directives: Option<DirectiveArguments<'a>>,
    pub is_block: bool,                       // openBlock/createBlock 対象か
    pub is_component: bool,
}
```

Angular が Operation ベースの IR で「何を実行するか」を表現するのに対し、Vue は VNodeCall で「どんな VNode を生成するか」を表現する。この違いは両フレームワークのランタイムアーキテクチャに直結している。

### 4. 変換オーケストレーションの違い

#### Angular: 静的フェーズ配列による順次実行

`crates/oxc_angular_compiler/src/pipeline/phases/mod.rs`:

```rust
pub struct Phase {
    pub kind: CompilationJobKind,
    pub run: fn(&mut ComponentCompilationJob<'_>),
    pub run_host: Option<fn(&mut HostBindingCompilationJob<'_>)>,
    pub name: &'static str,
}

pub static PHASES: &[Phase] = &[
    Phase { kind: Template, run: remove_content_selectors, name: "removeContentSelectors" },
    Phase { kind: Both, run: optimize_regular_expressions, name: "optimizeRegularExpressions" },
    // ... 67フェーズが静的配列で定義
];
```

全フェーズが `fn(&mut ComponentCompilationJob<'_>)` というシグネチャで統一され、静的配列として定義。各フェーズは `CompilationJob` 内の OpList を走査・変更する。

#### Vue: NodeTransform + ExitFn パターン

`crates/vize_atelier_core/src/transform/mod.rs`:

```rust
pub type NodeTransform<'a> =
    fn(&mut TransformContext<'a>, &mut TemplateChildNode<'a>) -> Option<std::vec::Vec<ExitFn<'a>>>;

pub type ExitFn<'a> = std::boxed::Box<dyn FnOnce(&mut TransformContext<'a>) + 'a>;

pub struct TransformContext<'a> {
    pub allocator: &'a Bump,
    pub parent: Option<ParentNode<'a>>,
    pub grandparent: Option<ParentNode<'a>>,
    pub current_node: Option<*mut TemplateChildNode<'a>>,
    pub helpers: FxHashSet<RuntimeHelper>,
    pub hoists: Vec<'a, Option<JsChildNode<'a>>>,
    pub cached: Vec<'a, Option<Box<'a, CacheExpression<'a>>>>,
    // ...
}
```

Vue は「enter 時に NodeTransform を実行 → ExitFn を返す → 子ノード処理後に ExitFn を実行」というビジター風パターン。Angular の「全ノードに対して1フェーズずつ順次適用」とは対照的。

### 5. ExpressionStore パターン（Angular 固有）

Angular コンパイラの独自設計で、式のクローンを避けるための Reference + Index パターン。

`crates/oxc_angular_compiler/src/pipeline/expression_store.rs`:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ExpressionId(pub u32);

pub struct ExpressionStore<'a> {
    expressions: Vec<'a, AngularExpression<'a>>,
}

impl<'a> ExpressionStore<'a> {
    pub fn store(&mut self, expr: AngularExpression<'a>) -> ExpressionId {
        let id = ExpressionId::new(self.expressions.len() as u32);
        self.expressions.push(expr);
        id
    }

    pub fn get(&self, id: ExpressionId) -> &AngularExpression<'a> {
        &self.expressions[id.index()]
    }
}
```

IR 内の各 Op は `ExpressionId` を保持し、実際の式は `ExpressionStore` に一元管理される。67フェーズが式を参照・変換する際にクローンが不要になる。

Vue にはこの仕組みがなく、`SimpleExpressionNode` を AST ノードに直接保持する。Vue の変換フェーズ数が少ないため、この最適化の必要性が低い。

### 6. 名前解決の違い

#### Angular: resolve_names フェーズ

`crates/oxc_angular_compiler/src/pipeline/phases/resolve_names.rs`:

```rust
#[derive(Default, Clone)]
struct ScopeMaps<'a> {
    scope: FxHashMap<Atom<'a>, XrefId>,
    local_definitions: FxHashMap<Atom<'a>, XrefId>,  // @let 宣言（優先度高）
}

impl<'a> ScopeMaps<'a> {
    fn get(&self, name: &Atom<'a>) -> Option<&XrefId> {
        // local_definitions を最初にチェック
        self.local_definitions.get(name).or_else(|| self.scope.get(name))
    }
}
```

`LexicalReadExpr` を `ReadVariableExpr`（スコープ内変数）または `PropertyRead(ContextExpr, name)`（コンポーネントプロパティ: `ctx.message`）に解決する。解決後、`verify_no_lexical_reads_remain` で未解決の参照がないことを検証。

#### Vue: transform_expression でのプレフィクス付与

Vue は `$setup.`、`$data.`、`$props.` などのプレフィクスを付与する方式。`BindingType`（`SetupConst`, `SetupRef`, `Props` 等）に基づいてプレフィクスを決定する。Angular のように独立したフェーズではなく、変換中にインラインで処理される。

### 7. 出力コードの根本的な違い

最も重要な設計差異。

#### Angular: Reify フェーズで Create/Update 分離した命令列を生成

`crates/oxc_angular_compiler/src/pipeline/phases/reify/mod.rs`:

```rust
fn reify_view_to_stmts<'a>(
    allocator: &'a Allocator,
    view: &mut ViewCompilationUnit<'a>,
    expressions: &ExpressionStore<'a>,
    pool: &mut ConstantPool<'a>,
    root_xref: XrefId,
    ctx: &ReifyContext<'a>,
    diagnostics: &mut Vec<OxcDiagnostic>,
) -> (std::vec::Vec<OutputStatement<'a>>, std::vec::Vec<OutputStatement<'a>>) {
    let mut create_stmts = std::vec::Vec::new();
    let mut update_stmts = std::vec::Vec::new();

    for op in view.create.iter_mut() {
        let stmt = reify_create_op(allocator, op, expressions, pool, root_xref, ctx, diagnostics);
        if let Some(s) = stmt { create_stmts.push(s); }
    }
    for op in view.update.iter() {
        let stmt = reify_update_op(allocator, op, expressions, root_xref, ctx.mode, diagnostics);
        if let Some(s) = stmt { update_stmts.push(s); }
    }
    (create_stmts, update_stmts)
}
```

`crates/oxc_angular_compiler/src/pipeline/emit.rs` で最終的なテンプレート関数に組み立てる：

```rust
fn emit_view<'a>(allocator: &'a Allocator, view: &ViewCompilationUnit<'a>) -> FunctionExpr<'a> {
    let create_statements = clone_statements(allocator, &view.create_statements);
    let update_statements = clone_statements(allocator, &view.update_statements);
    // rf & 1: 作成フェーズ、rf & 2: 更新フェーズ
    let create_block = maybe_generate_rf_block(allocator, 1, create_statements);
    let update_block = maybe_generate_rf_block(allocator, 2, update_statements);
    // ...
}
```

出力:

```javascript
function AppComponent_Template(rf, ctx) {
    if (rf & 1) { ɵɵelementStart(0, "div"); ɵɵtext(1); ɵɵelementEnd(); }
    if (rf & 2) { ɵɵtextInterpolate(ctx.message); }
}
```

#### Vue: VNodeCall を render 関数として出力

`crates/vize_atelier_core/src/codegen.rs`:

```rust
pub fn generate(root: &RootNode<'_>, options: CodegenOptions) -> CodegenResult {
    let mut ctx = CodegenContext::new(options);
    generate_function_signature(&mut ctx);
    ctx.push("return ");

    if root.children.len() == 1 {
        generate_root_node(&mut ctx, &root.children[0]);
    } else {
        // 複数ルート → Fragment でラップ
        ctx.push("(");
        ctx.push(ctx.helper(RuntimeHelper::OpenBlock));
        ctx.push("(), ");
        ctx.push(ctx.helper(RuntimeHelper::CreateElementBlock));
        ctx.push("(");
        ctx.push(ctx.helper(RuntimeHelper::Fragment));
        ctx.push(", null, [...], 64 /* STABLE_FRAGMENT */))");
    }
    // ...
}
```

出力:

```javascript
function render(_ctx, _cache, $props, $setup) {
  return (_openBlock(), _createElementBlock("div", null,
    _toDisplayString($setup.message), 1 /* TEXT */))
}
```

**根本的な違い**: Angular は「作成（1回）と更新（毎回）を分離した命令列 → 直接 DOM 操作」、Vue は「毎回 VNode ツリーを返す → Virtual DOM diff でパッチ」。

### 8. 最適化戦略の違い

#### Vue: Patch Flags と Static Hoisting

`crates/vize_atelier_core/src/codegen/element.rs` での Patch Flag 計算:

```rust
let (patch_flag, dynamic_props) = calculate_element_patch_info(
    el,
    ctx.options.binding_metadata.as_ref(),
    ctx.options.cache_handlers,
);
// 出力例: 1 /* TEXT */, 9 /* TEXT, PROPS */
```

`crates/vize_atelier_core/src/transforms/hoist_static.rs` での静的判定:

```rust
pub fn is_static_node(node: &TemplateChildNode<'_>) -> bool {
    match node {
        TemplateChildNode::Text(_) => true,
        TemplateChildNode::Comment(_) => true,
        TemplateChildNode::Element(el) => is_static_element(el),
        TemplateChildNode::Interpolation(_) => false,  // {{ }} は常に動的
        TemplateChildNode::If(_) => false,
        TemplateChildNode::For(_) => false,
        _ => false,
    }
}

fn is_static_element(el: &ElementNode<'_>) -> bool {
    if el.tag_type != ElementType::Element { return false; }
    // ディレクティブが1つでもあれば非静的
    for prop in el.props.iter() {
        if let PropNode::Directive(_) = prop { return false; }
    }
    // 子要素がすべて静的テキストなら静的
    for child in el.children.iter() {
        if !is_static_node(child) { return false; }
    }
    true
}
```

静的ノードはモジュールスコープに巻き上げられ、render 関数から参照のみになる:

```javascript
const _hoisted_1 = /*#__PURE__*/ _createElementVNode("span", null, "Static text")
function render(_ctx) { return _createElementBlock("div", null, [_hoisted_1, ...]) }
```

#### Angular: 定数プール + 純関数抽出

Angular では Patch Flag の代わりに Create/Update 分離が根本的な最適化。加えて `const_collection` フェーズで要素属性を定数配列にまとめ、`pure_function_extraction` フェーズでメモ化可能な純関数を抽出する。`allocate_slots` フェーズでスロット ID を割り当て、ランタイムが直接 DOM ノードにアクセスできるようにする。

### 9. 構造的ディレクティブの処理

#### Vue: v-if → IfNode への構造変換

`crates/vize_atelier_core/src/transforms/v_if.rs`:

```rust
pub fn has_v_if(el: &ElementNode<'_>) -> bool {
    el.props.iter().any(|prop| matches!(prop, PropNode::Directive(dir) if dir.name == "if"))
}

pub fn process_v_if(ctx: &mut TransformContext<'_>) {
    ctx.helper(RuntimeHelper::OpenBlock);
    ctx.helper(RuntimeHelper::CreateBlock);
    ctx.helper(RuntimeHelper::CreateElementBlock);
    ctx.helper(RuntimeHelper::Fragment);
    ctx.helper(RuntimeHelper::CreateComment);  // v-else 用のコメントプレースホルダ
}
```

v-for の式パース（`crates/vize_atelier_core/src/transforms/v_for.rs`）:

```rust
pub fn parse_for_expression<'a>(
    allocator: &'a Bump,
    content: &str,
    loc: &SourceLocation,
) -> ForParseResult<'a> {
    // "item in items" or "(item, index) in items" をパース
    let (alias_part, source_part) = if let Some(idx) = content.find(" in ") {
        (&content[..idx], &content[idx + 4..])
    } else if let Some(idx) = content.find(" of ") {
        (&content[..idx], &content[idx + 4..])
    } else { /* ... */ };
    // "(item, index)" → value=item, key=index に分解
    // ...
}
```

#### Angular: @if/@for → ConditionalOp/RepeaterCreateOp

Angular は HTML パーサーレベルで `@if`/`@for` ブロック構文を認識し、R3 AST の `IfBlock`/`ForLoopBlock` に変換。その後 ingest フェーズで `ConditionalOp`/`RepeaterCreateOp` の IR に変換される。Vue の「AST ノードを別のノードに置換」とは異なり、「IR 操作として列挙」するアプローチ。

### 10. メモリ管理

両者ともアリーナアロケータを使用するが、ソースが異なる。

- **Angular**: `oxc_allocator::Allocator`（OXC 提供、bumpalo ベース）
- **Vue**: `bumpalo::Bump` を直接使用

Angular は OXC の `Box<'a, T>` と `Vec<'a, T>` を使い、Vue は `vize_carton` クレートで独自のバンプ割り当てコンテナを提供。

Angular 特有の設計として、ExpressionStore + ExpressionId パターンにより、67フェーズ間で式のクローンが不要。Vue は変換フェーズが少ないため、AST ノードに式を直接保持しても問題にならない。

### 11. ParentNode パターン（Vue 固有）

Vue の変換では、再帰的なツリー走査中に親ノードへの可変参照が必要になる。Rust の借用規則と衝突するため、生ポインタを使った `ParentNode` enum で解決している。

`crates/vize_atelier_core/src/transform/mod.rs`:

```rust
#[derive(Clone, Copy)]
pub enum ParentNode<'a> {
    Root(*mut RootNode<'a>),
    Element(*mut ElementNode<'a>),
    IfBranch(*mut IfBranchNode<'a>),
    For(*mut ForNode<'a>),
}

impl<'a> ParentNode<'a> {
    pub fn children_mut(&self) -> &mut Vec<'a, TemplateChildNode<'a>> {
        unsafe {
            match self {
                ParentNode::Root(r) => &mut (*(*r)).children,
                ParentNode::Element(e) => &mut (*(*e)).children,
                // ...
            }
        }
    }
}
```

Angular は OpList のカーソルパターンで同様の問題を回避しており、生ポインタは `NonNull<T>` として OpList 内部に閉じている。

### 12. プロジェクトスコープの違い

| 機能 | Vize | OXC Angular |
|---|---|---|
| テンプレートコンパイラ | ✅ | ✅ |
| SFC パーサー | ✅ (`vize_armature`) | ❌（Angular は SFC なし） |
| リンター | ✅ (`vize_patina`, 55+ ルール) | ❌ |
| フォーマッター | ✅ | ❌ |
| 型チェッカー | ✅（tsgo 連携） | ❌ |
| LSP | ✅ (`vize_maestro`) | ❌ |
| Storybook 風機能 | ✅ (`vize_musea`) | ❌ |
| TUI フレームワーク | ✅ (`vize_fresco`) | ❌ |
| WASM バインディング | ✅ | ❌ |
| Vapor モード | ✅ | ❌ |
| i18n | ❌ | ✅（XLIFF/XMB） |

Vize は Vue 開発ツールチェーン全体を Rust で構築する野心的プロジェクト。OXC Angular Compiler はコンパイラに特化し、Vite プラグインとの統合に注力している。

## ポイント

- Angular は専用 IR（CreateOp/UpdateOp のダブルリンクリスト）を持ち、67フェーズで段階的に変換する。Vue は AST を直接変換し、VNodeCall をコードジェンノードとして付与する
- Angular の出力は Create/Update 分離の命令列（直接 DOM 操作）、Vue の出力は VNode ツリーを返す render 関数（Virtual DOM diff）
- Vue の Patch Flags は Virtual DOM diff の高速化手段。Angular には Create/Update 分離があるため、この概念自体が不要
- Angular の ExpressionStore + ExpressionId パターンは、多数のフェーズ間で式を参照する際のクローンコストを排除する設計
- Vue の ParentNode（生ポインタ）と Angular の OpListCursor（NonNull ベースのカーソル）は、Rust の借用規則と可変ツリー走査の衝突を異なるアプローチで解決している
- 両プロジェクトとも OXC / bumpalo + NAPI-RS + Vite が Rust 製フロントエンドツールの定番スタックになりつつある
- 「Ivy を置き換える」のではなく「Ivy コンパイラを Rust で高速化する」という区別が重要。出力は同じ Ivy ランタイム命令

## 参考

- [voidzero-dev/oxc-angular-compiler](https://github.com/voidzero-dev/oxc-angular-compiler)
- [ubugeeei/vize](https://github.com/ubugeeei/vize)
- [OXC](https://github.com/oxc-project/oxc)
