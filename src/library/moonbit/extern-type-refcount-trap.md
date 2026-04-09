# MoonBit ネイティブで `pub type` の extern ポインタを渡すと rc 操作で隣接メモリが破壊される

## 概要

MoonBit のネイティブバックエンド（0.6 系）で `pub type Foo` として宣言した extern C 型を、通常の関数の引数として渡すと、コンパイラが関数末尾に `moonbit_decref` を自動挿入する。中身が `libc_malloc` 由来で `moonbit_object` ヘッダを持たないポインタだった場合、その decref は `(ptr - 8)` の 4 バイトを `rc - 1` として書き戻し、隣接する String バッファの先頭 codeunit を破壊する。`moonbit_make_external_object` でラップしてダミー rc ヘッダを与えると解決する。

## 背景・きっかけ

SQLite を叩く CLI ツールで、特定のクエリの戻り値だけ「先頭バイトが 1 だけずれる」という決定的な破壊が発生した。`91` が `81` に、`ひこう` が `ぱこう` に化ける。SQL を直接叩くと正しく返ってくる。C 側で `sqlite3_column_text` の直後に生バイトをダンプすると正しい。しかし MoonBit 側で String を受け取った時点ですでに先頭 codeunit だけ `-1` されている。

`debug` ビルドでは再現せず、`--release` ビルドでのみ再現する、という挙動から malloc のアロケーションパターン依存のメモリ破壊だと当たりを付けた。

## 学んだこと

### extern C 型の宣言と rc の扱い

`ffi.mbt` で SQLite のリザルトセットを次のように宣言していた:

```moonbit
pub type ResultSet

#borrow(rs)
extern "C" fn pkdx_result_get(rs : ResultSet, row : Int, col : Int) -> String = "pkdx_result_get"
```

`#borrow(rs)` は `extern "C" fn` に付けた場合は有効で、FFI 境界では incref/decref が挿入されない。ここまでは正しい。

ところが、このまま `ResultSet` を **通常の MoonBit 関数** の引数として渡すと挙動が変わる:

```moonbit
pub fn get_string(rs : ResultSet, row : Int, col : Int) -> String {
  pkdx_result_get(rs, row, col)
}
```

生成された C コードを見ると:

```c
moonbit_string_t get__string(void* rs, int32_t row, int32_t col) {
  moonbit_string_t result = pkdx_result_get(rs, row, col);
  if (rs) { moonbit_decref(rs); }   // ← 自動挿入される
  return result;
}
```

`ResultSet` は `pub type` で宣言された不透明な extern 型だが、コンパイラはそれを一律に refcounted オブジェクトとして扱い、関数末尾で `moonbit_decref` を挿入する。`#borrow` アノテーションは MoonBit 通常関数には使えないので、この挿入を抑止する手段がない。

### `moonbit_decref` が隣接メモリを壊す仕組み

MoonBit ランタイムの `moonbit_decref` の実装はこう:

```c
void moonbit_decref(void *ptr) {
  struct moonbit_object *header = Moonbit_object_header(ptr);
  int32_t const count = header->rc;
  if (count > 1) {
    header->rc = count - 1;
  } else if (count == 1) {
    moonbit_drop_object(ptr);
  }
}
```

`Moonbit_object_header(ptr)` は `((struct moonbit_object*)ptr) - 1`、つまり `ptr - 8` を返す（`struct moonbit_object` は `int32_t rc; uint32_t meta;` で 8 バイト）。通常のヒープオブジェクトは必ず `moonbit_malloc_array` 経由で確保され、直前にヘッダ領域が取られている前提。

しかし今回の `ResultSet` は C 側で普通に `libc_malloc(sizeof(PkdxResultSet))` していた:

```c
PkdxResultSet *pkdx_null_rs(void) {
    PkdxResultSet *rs = (PkdxResultSet *)libc_malloc(sizeof(PkdxResultSet));
    // ...
    return rs;
}
```

なのでヘッダは存在せず、`(rs - 8)` は他のアロケーションの末尾（malloc のブックキーピングや、直前に確保された別オブジェクトのデータ領域）に落ちる。`moonbit_decref(rs)` が呼ばれると、そこに置かれていた 4 バイトが `count - 1` として書き戻される。

malloc の 並びが「直前に確保された String バッファの先頭 4 バイト」と重なる構成になったとき、書き換えは `データ[0..3] = データ[0..3] - 1` と等価な挙動を見せる（実際には古い値を rc と誤認して -1 しているだけだが、エンディアンの都合で末尾バイトが変化する）。UTF-16 の先頭 codeunit 1 ユニットだけが `-1` される、という決定的な破壊パターンはここから来る:

- `'9'`(`0x0039`) → `'8'`(`0x0038`)
- `'ひ'`(`0x3072`) → `'ぱ'`(`0x3071`)

### 正しい解決策: `moonbit_make_external_object`

MoonBit ランタイムには、C 側でリソースを確保しつつも「MoonBit から見ると正規のオブジェクト」として扱える仕組みが用意されている:

```c
MOONBIT_EXPORT void *moonbit_make_external_object(
  void (*finalize)(void *self),
  uint32_t payload_size
);
```

これを使うと、確保されたポインタの直前に正規の `moonbit_object` ヘッダ（rc と meta）が書き込まれ、末尾に finalize 関数ポインタが置かれる。rc が 0 になった時点で `finalize` が呼ばれる。

今回の修正はこれだけ:

```c
static void pkdx_rs_destructor(void *self) {
    PkdxResultSet *rs = (PkdxResultSet *)self;
    if (!rs->cells) return;
    int32_t total = rs->row_count * rs->col_count;
    for (int32_t i = 0; i < total; i++) {
        if (rs->cells[i]) libc_free(rs->cells[i]);
    }
    libc_free(rs->cells);
    rs->cells = NULL;
}

PkdxResultSet *pkdx_null_rs(void) {
    PkdxResultSet *rs = (PkdxResultSet *)moonbit_make_external_object(
        &pkdx_rs_destructor, sizeof(PkdxResultSet));
    rs->row_count = 0;
    rs->col_count = 0;
    rs->cells = NULL;
    return rs;
}
```

`(rs - 8)` に正規の rc/meta ヘッダが置かれるので、MoonBit が挿入するどんな incref/decref も自分自身のヘッダに閉じる。他メモリの破壊が起きなくなる。

### release ビルドでしか再現しない理由

同じ rc 誤動作は debug ビルドでも起きているはずだが、debug では allocator が保守的（ガード領域やアラインメントが多い、malloc メタデータのレイアウトが違う）で、`(rs - 8)` が他オブジェクトのデータとぴったり重ならず、書き換えた値が運良く無害な場所に落ちる。release ビルドで最適化が効くと allocator の挙動も変わり、決定的に他オブジェクトの先頭にヒットする配置になる。

このクラスのメモリ破壊バグを回帰テストで守る場合、必ず `--release` で走らせる必要がある:

```bash
moon test --target native --release
```

### テスト側からの FFI シンボル解決

回帰テストを書こうとしたとき、テストパッケージから FFI シンボルが解決できず `tcc: error: undefined symbol '_pkdx_db_open'` 系のリンクエラーになった。

MoonBit の `moon.pkg` では C スタブをパッケージ単位で `native-stub` として登録する:

```
options(
  "supported-targets": "native",
  "native-stub": [ "cwrap.c", "sqlite3.c" ],
  link: {
    "native": {
      "stub-cc-flags": "-DSQLITE_THREADSAFE=0 ...",
    },
  },
)
```

重要な制約:

- `native-stub` のパスは **パッケージディレクトリからの相対** で、`..` を含むパスは許可されない（`Path descends into parent directory` エラーになる）
- テストコード（`*_test.mbt`）は属するパッケージの `native-stub` しか見えないので、FFI を叩くテストは C ファイルと同じパッケージに置く必要がある

今回は `src/main/cwrap.c` にあった C ファイルを `src/db/cwrap.c` に移し、db パッケージの `native-stub` に登録することでテストから FFI が見えるようにした。main は db に依存するので最終バイナリのリンクには影響しない。

### テスト専用 import

`moonbitlang/x/sys` のような本体では使わないパッケージをテスト側だけで使うには `for "test"` 付きの import を別ブロックで書く:

```
import {
  "ushironoko/pkdx/src/model",
}

import {
  "moonbitlang/x/sys",
} for "test"
```

## ポイント

- MoonBit の `pub type Foo` は通常の関数引数として渡した瞬間 refcounted 扱いになる。中身が `libc_malloc` 由来のポインタなら `moonbit_make_external_object` でラップしないと即 UB
- `#borrow` は `extern "C" fn` にしか効かない。MoonBit 側のラッパー関数では decref 挿入を抑止できない
- `moonbit_decref` は `(ptr - 8)` の 4 バイトを書き換える。これが他オブジェクトと重なるとアロケーションパターン依存のメモリ破壊になる
- アロケーションパターン依存のバグは debug では再現せず release でしか出ないことがある。回帰テストは必ず `--release` で走らせる
- `native-stub` はパッケージ単位で、`..` 相対パス禁止。FFI を叩くテストはスタブと同じパッケージに置く
- テスト専用の import は `for "test"` ブロックで分離する

## 参考

- MoonBit ランタイムヘッダ: `~/.moon/include/moonbit.h`
- MoonBit ランタイム実装: `~/.moon/lib/runtime.c`（`moonbit_decref` / `moonbit_drop_object` / `moonbit_make_external_object`）
- 修正コミット: `ushironoko/pkdx@f8cfae3` fix(ffi): wrap PkdxResultSet as moonbit external object
- リグレッションテスト: `ushironoko/pkdx@d7f484f` test(db): add integration test for query_pokemon rc-bug regression
