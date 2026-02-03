# tree-sitter vs syntect によるシンタックスハイライト

## 概要

Rust TUIアプリケーションでシンタックスハイライトを実装する際の、tree-sitter（CSTベース）と syntect（正規表現ベース）の使い分けと、TextMate 文法・Sublime Syntax の関係について。

## 背景・きっかけ

octorus（GitHub PRレビューTUIツール）で diff のシンタックスハイライトを実装する際、主要言語には tree-sitter を使用し、それ以外の言語には syntect をフォールバックとして使用するハイブリッドアプローチを採用した。

## 学んだこと

### シンタックスハイライトの歴史的背景

#### TextMate 文法 (.tmLanguage / .plist)

TextMate（macOS エディタ）が導入した**正規表現ベースの文法定義形式**。XML/plist形式で記述される。

- **スコープ**: `source.rust`, `keyword.control`, `string.quoted.double` など階層的な名前空間
- **パターン**: 正規表現でマッチングルールを定義
- **ネスト**: `begin`/`end` パターンで複数行にまたがるマッチが可能

多くのエディタ（VS Code, Sublime Text, Atom など）がこの形式を採用し、事実上の標準となった。

#### Sublime Syntax (.sublime-syntax)

Sublime Text 3 が導入した**YAML ベースの改良版文法定義**。

- TextMate 文法との後方互換性を維持
- YAML 形式で可読性が向上
- `push`/`pop`/`set` によるコンテキストスタック操作
- より表現力の高いパターン定義が可能

```yaml
# .sublime-syntax の例
scope: source.rust
contexts:
  main:
    - match: \b(fn|let|mut|const)\b
      scope: keyword.control.rust
    - match: '"'
      push: string
  string:
    - meta_scope: string.quoted.double.rust
    - match: '"'
      pop: true
```

#### TextMate テーマ (.tmTheme)

スコープ名に対するスタイル（色、太字、斜体など）を定義する XML ファイル。

```xml
<dict>
  <key>scope</key>
  <string>keyword.control</string>
  <key>settings</key>
  <dict>
    <key>foreground</key>
    <string>#FF79C6</string>
    <key>fontStyle</key>
    <string>bold</string>
  </dict>
</dict>
```

### syntect の仕組み

syntect は **Sublime Syntax (.sublime-syntax) パーサー**を Rust で実装したライブラリ。

**構成要素:**
- `SyntaxSet`: 複数の言語定義を保持するコンテナ
- `ThemeSet`: 複数のテーマを保持するコンテナ
- `HighlightLines`: ステートフルなハイライター（行ごとに状態を保持）

```rust
// syntect の基本的な使い方
let ss = SyntaxSet::load_defaults_newlines();
let ts = ThemeSet::load_defaults();

let syntax = ss.find_syntax_by_extension("rs").unwrap();
let theme = &ts.themes["base16-ocean.dark"];
let mut highlighter = HighlightLines::new(syntax, theme);

let line = "fn main() {";
let ranges = highlighter.highlight_line(line, &ss)?;
// ranges: Vec<(Style, &str)> - スタイル付きテキスト断片
```

**テーマの読み込み:**

```rust
// 複数ソースからテーマを読み込む
fn load_all_themes() -> ThemeSet {
    let mut themes = ThemeSet::load_defaults();  // syntect デフォルト

    // バンドルテーマ（.tmTheme）
    if let Ok(theme) = ThemeSet::load_from_reader(&mut Cursor::new(DRACULA_THEME)) {
        themes.themes.insert("Dracula".to_string(), theme);
    }

    // ユーザーテーマ（~/.config/app/themes/*.tmTheme）
    for entry in read_dir(user_themes_dir) {
        if path.extension() == "tmTheme" {
            let theme = ThemeSet::get_theme(&path)?;
            themes.themes.insert(name, theme);
        }
    }

    themes
}
```

**two-face クレートによる拡張:**

`two-face` は [bat](https://github.com/sharkdp/bat) の Sublime Syntax 定義をバンドルしたクレート。

```rust
// two-face で拡張構文を取得
let ss = two_face::syntax::extra_newlines();  // 200+ 言語対応
```

### tree-sitter の仕組み

tree-sitter は**具体構文木（CST）パーサージェネレータ**。正規表現ではなく、文脈自由文法に基づく。

**構成要素:**
- `Language`: コンパイル済みパーサー（言語固有クレート）
- `Parser`: パース実行エンジン
- `Tree`: パース結果の構文木
- `Query`: キャプチャパターン定義

```rust
// tree-sitter の基本的な使い方
let mut parser = Parser::new();
parser.set_language(&tree_sitter_rust::LANGUAGE.into())?;

let tree = parser.parse("fn main() {}", None).unwrap();
let query = Query::new(&language, tree_sitter_rust::HIGHLIGHTS_QUERY)?;

let mut cursor = QueryCursor::new();
for match in cursor.matches(&query, tree.root_node(), source.as_bytes()) {
    for capture in match.captures {
        let capture_name = &query.capture_names()[capture.index];
        // capture_name: "keyword", "function", "type" など
    }
}
```

**HIGHLIGHTS_QUERY の例（Rust）:**

```scheme
; tree-sitter のクエリ言語（S式）
(function_item
  name: (identifier) @function)

["fn" "let" "mut" "const"] @keyword

(string_literal) @string
```

### 比較表

| 特性 | tree-sitter | syntect (Sublime Syntax) |
|------|------------|-------------------------|
| **パース方式** | CST（構文木） | 正規表現（ステートマシン） |
| **精度** | 高い（構文的に正確） | 中程度（正規表現の限界） |
| **言語追加** | パーサー実装が必要 | .sublime-syntax ファイルのみ |
| **メモリ** | 大（約200KB/言語） | 小 |
| **テーマ形式** | 独自マッピング必要 | .tmTheme 直接対応 |
| **エコシステム** | 言語ごとのクレート | bat/Sublime の資産を活用 |

### スコープからスタイルへのマッピング

syntect は TextMate スコープをそのまま使用するが、tree-sitter は独自のキャプチャ名を使用するため、マッピングが必要。

```rust
// tree-sitter キャプチャ名 → TextMate スコープへのマッピング
fn capture_to_scope(capture_name: &str) -> &'static [&'static str] {
    match capture_name {
        "keyword" => &["keyword", "keyword.control"],
        "function" => &["entity.name.function"],
        "type" => &["entity.name.type", "support.type"],
        "string" => &["string", "string.quoted"],
        "comment" => &["comment"],
        _ => &[],
    }
}
```

### TypeScript の特殊対応

TypeScript の tree-sitter クエリは JavaScript クエリを継承する前提で設計されている。

```rust
static TYPESCRIPT_COMBINED_QUERY: LazyLock<String> = LazyLock::new(|| {
    format!(
        "{}\n{}",
        tree_sitter_javascript::HIGHLIGHT_QUERY,  // JavaScript パターン
        tree_sitter_typescript::HIGHLIGHTS_QUERY   // TypeScript 固有パターン
    )
});
```

### ハイブリッドアプローチ

```rust
pub enum Highlighter<'a> {
    /// tree-sitter CST highlighter for supported languages.
    Cst { parser, language, query_source, capture_names, style_cache },
    /// Syntect regex-based highlighter for fallback.
    Syntect(HighlightLines<'a>),
    /// No highlighting available.
    None,
}
```

**選択ロジック:**
1. `SupportedLanguage::from_extension(ext)` で tree-sitter 対応を確認
2. 対応していれば tree-sitter (Cst)
3. 非対応なら `syntax_for_file()` で syntect を試行
4. どちらも非対応なら None

## ポイント

- **TextMate 文法**: エディタ界の事実上の標準。.tmLanguage (XML) と .tmTheme で構成
- **Sublime Syntax**: YAML ベースの改良版。bat/two-face で広く利用
- **syntect**: Sublime Syntax パーサーの Rust 実装。テーマは .tmTheme を直接使用
- **tree-sitter**: 構文木ベースで高精度だが、スコープマッピングが別途必要
- **ハイブリッド**: 主要言語は tree-sitter、それ以外は syntect でカバーが実用的

## 参考

- [TextMate Language Grammars](https://macromates.com/manual/en/language_grammars)
- [Sublime Syntax Definitions](https://www.sublimetext.com/docs/syntax.html)
- [tree-sitter/tree-sitter](https://github.com/tree-sitter/tree-sitter)
- [trishume/syntect](https://github.com/trishume/syntect)
- [sharkdp/bat](https://github.com/sharkdp/bat)
- [CosmicHorrorDev/two-face](https://github.com/CosmicHorrorDev/two-face)
