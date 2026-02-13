# SFCコンパイラの行ベースパーサーで踏んだ落とし穴

## 概要

Vue SFCコンパイラ（Rust実装）の `<script setup>` 行ベースパーサーで発見した複数のバグと、その修正パターンをまとめる。ナイーブなテキスト解析が実際のTypeScript/CSS構文でどう壊れるかの事例集。

## 背景・きっかけ

Vizeプロジェクト（Vue SFCをRustでコンパイルするツールチェイン）の大規模バリデーション中に、実プロダクションコードで複数のコンパイルバグが発覚した。いずれも「文字単位/行単位のナイーブなパターンマッチ」が原因。

## 学んだこと

### 1. アロー関数 `=>` が山括弧カウントを壊す

**問題**: TypeScript型宣言の深さを `<` / `>` の出現回数で追跡していた。

```rust
// BAD: `=>` の `>` も閉じ山括弧としてカウントされる
ts_type_depth += trimmed.matches('<').count() as i32;
ts_type_depth -= trimmed.matches('>').count() as i32;
```

`onClick: () => void` という行で `>` が1つカウントされ、`ts_type_depth` が想定より早く0に到達。型宣言の閉じ `}` がsetupボディに漏れ、OXCパースエラーを引き起こした。

**修正**: カウント前に `=>` を無害な文字列に置換する。

```rust
// GOOD: アロー演算子を除外してからカウント
let line_no_arrow = trimmed.replace("=>", "__");
ts_type_depth += line_no_arrow.matches('<').count() as i32;
ts_type_depth -= line_no_arrow.matches('>').count() as i32;
```

**教訓**: 単一文字のカウントは、その文字が複数文字トークンの一部である場合に壊れる。`>>` (ビットシフト)、`>=` (比較)、`=>` (アロー) すべてが罠になりうる。

### 2. `@keyframes` 内のキーフレームストップにスコープIDが付く

**問題**: Scoped CSS処理が `@media` と `@keyframes` を同じ「at-ruleブロック」として扱い、`from`/`to`/`0%`/`100%` をCSSセレクタとしてスコープIDを付与していた。

```css
/* 期待 */
@keyframes spin { from { transform: rotate(0) } }

/* 実際の出力 */
@keyframes spin { from[data-v-abc123] { transform: rotate(0) } }
```

**修正**: `brace_depth` を使って `@keyframes` ブロックの内外を追跡する。

```rust
let mut keyframes_brace_depth: Option<u32> = None;

// @keyframes 検出時
'@' => {
    let remaining = &css[i+1..];
    pending_keyframes = remaining.starts_with("keyframes")
        || remaining.starts_with("-webkit-keyframes")
        || remaining.starts_with("-moz-keyframes")
        || remaining.starts_with("-o-keyframes");
}

// { に遭遇時
'{' => {
    if pending_keyframes {
        keyframes_brace_depth = Some(brace_depth);
    } else if keyframes_brace_depth.is_some_and(|d| brace_depth > d) {
        // @keyframes内部: セレクタスコープをスキップ
        in_selector = false;
    }
}
```

**教訓**: CSS at-ruleは一律に処理できない。`@media`/`@supports` のブロック内セレクタはスコープ対象だが、`@keyframes` のブロック内はセレクタではない。ベンダープレフィックス（`@-webkit-keyframes` 等）も忘れずに。

### 3. 空クォート属性値がbooleanになる

**問題**: `alt=""` のようなHTML属性で、トークナイザーが空文字列の `on_attrib_data` コールバックを発火しない設計だった。パーサーは `value_start`/`value_end` が `None` → boolean属性（`alt: true`）と判定。

**修正**: クォートタイプの情報を活用する。

```rust
// finish_attribute() 内
} else if matches!(quote, QuoteType::Double | QuoteType::Single) {
    // alt="" → 空文字列（boolean "true" にしない）
    let empty_loc = self.create_loc(end, end);
    attr_node.value = Some(TextNode::new("", empty_loc));
}
```

**教訓**: 「値がない」と「空の値がある」は異なる状態。`<input disabled>` (boolean) と `<img alt="">` (空文字列) の区別にはクォートの有無が情報源になる。

### 4. import hoistingで静的アセットURLを解決する

**問題**: テンプレート内の `src="@/assets/logo.svg"` がコンパイル後も文字列リテラルのまま残り、Viteのエイリアス解決を通らない。

**修正**: `@vitejs/plugin-vue` と同じ手法 — import文に変換してViteのモジュール解決パイプラインに乗せる。

```typescript
// Before
const _hoisted_1 = { src: "@/assets/images/logo.svg", alt: "" };

// After
import __vize_static_0 from "@/assets/images/logo.svg";
const _hoisted_1 = { src: __vize_static_0, alt: "" };
```

**教訓**: Viteプラグインでアセットパスを解決したい場合、`/@fs/` パス置換よりもimport文生成のほうがdev/build両対応でき、Viteの標準パイプラインに自然に乗る。

## ポイント

- 行ベース/文字ベースのテキスト解析は、実プロダクションコードの多様な構文パターンで容易に壊れる
- 「文字の出現回数カウント」は複数文字トークン（`=>`、`>>`、`>=`）の存在を考慮する必要がある
- CSS at-ruleは種類ごとに意味論が異なる — `@media` と `@keyframes` を同一視してはならない
- HTML属性の「値なし」vs「空値」の区別には、クォートの有無という文脈情報が不可欠
- Viteのモジュール解決に乗せるにはimport文生成が最も自然なパターン
