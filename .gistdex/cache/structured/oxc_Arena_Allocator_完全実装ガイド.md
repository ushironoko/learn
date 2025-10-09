# oxc Arena Allocator 完全実装ガイド

## 目次

1. [概要](#概要)
2. [クレート構造](#クレート構造)
3. [コア実装](#コア実装)
4. [データ構造](#データ構造)
5. [API リファレンス](#api-リファレンス)
6. [高度な機能](#高度な機能)
7. [パフォーマンス最適化](#パフォーマンス最適化)
8. [使用例](#使用例)

---

## 概要

### 基本情報

- **クレート名**: `oxc_allocator`
- **場所**: `docs/oxc/crates/oxc_allocator/`
- **ベースライブラリ**: `bumpalo` (Rust の bump allocator)
- **アロケーション戦略**: Bump pointer allocation

### アーキテクチャ概要

oxc は高速な JavaScript/TypeScript toolchain であり、その性能を支える重要なコンポーネントが **Arena Allocator** です。AST ノードやその他のパース結果を高速に割り当てるために設計されています。

---

## クレート構造

### ファイル構成

```
oxc_allocator/
├── src/
│   ├── lib.rs                    # モジュール定義とエクスポート
│   ├── allocator.rs              # 核心の Allocator 実装
│   ├── allocator_api2.rs         # Rust Allocator API サポート
│   ├── vec.rs                    # Arena-based Vec
│   ├── boxed.rs                  # Arena-based Box
│   ├── hash_map.rs               # Arena-based HashMap
│   ├── hash_set.rs               # Arena-based HashSet
│   ├── string_builder.rs         # Arena-based StringBuilder
│   ├── pool/                     # AllocatorPool 実装
│   │   ├── mod.rs
│   │   ├── standard.rs           # StandardAllocatorPool
│   │   └── fixed_size.rs         # FixedSizeAllocatorPool
│   ├── clone_in.rs               # CloneIn トレイト
│   ├── take_in.rs                # TakeIn トレイト
│   ├── from_raw_parts.rs         # 内部構造へのアクセス
│   ├── tracking.rs               # アロケーション追跡
│   ├── bitset.rs                 # BitSet (オプション)
│   └── ...
```

### モジュール一覧

**ファイル**: `src/lib.rs` (行 1-89)

```rust
// 主要なエクスポート
pub use accessor::AllocatorAccessor;
pub use address::{Address, GetAddress};
pub use allocator::Allocator;           // ← 核心
pub use boxed::Box;
pub use clone_in::CloneIn;
pub use hash_map::HashMap;
pub use hash_set::HashSet;
pub use pool::*;                        // ← AllocatorPool
pub use string_builder::StringBuilder;
pub use take_in::{Dummy, TakeIn};
pub use vec::Vec;

#[cfg(feature = "bitset")]
pub use bitset::BitSet;
```

### フィーチャーフラグ

| フィーチャー | 説明 | デフォルト |
|------------|------|----------|
| `serialize` | `serde` と `oxc_estree` によるシリアライゼーションサポート | 無効 |
| `pool` | `AllocatorPool` を有効化 | 無効 |
| `bitset` | `BitSet` を有効化 | 無効 |
| `from_raw_parts` | `Allocator::from_raw_parts` メソッドを追加 | 無効 |
| `fixed_size` | 固定サイズアロケータを使用（64bit LE のみ） | 無効 |
| `track_allocations` | 割り当て回数を追跡（内部使用のみ） | 無効 |
| `disable_track_allocations` | `track_allocations` を無効化 | 無効 |

---

## コア実装

### 1. Allocator 構造体

**ファイル**: `src/allocator.rs` (行 222-227)

```rust
pub struct Allocator {
    bump: Bump,  // bumpalo::Bump をラップ
    /// 割り当て統計（track_allocations フィーチャーが有効な場合）
    #[cfg(all(feature = "track_allocations", not(feature = "disable_track_allocations")))]
    pub(crate) stats: AllocationStats,
}
```

**設計ポイント**:
- `bumpalo::Bump` を薄くラップした設計
- すべての主要メソッドに `#[inline(always)]` を適用
- 統計機能はオプション

### 2. ChunkFooter（内部実装）

**ファイル**: `src/from_raw_parts.rs` (行 354-375)

```rust
struct ChunkFooter {
    /// チャンクの開始位置へのポインタ
    /// このフッターは常にチャンクの終端に配置される
    data: NonNull<u8>,

    /// チャンクのレイアウト情報
    layout: Layout,

    /// 前のチャンクへのリンク（リンクリスト構造）
    /// 最後のノードは自分自身を指す（canonical empty chunk）
    prev: Cell<NonNull<ChunkFooter>>,

    /// バンプポインタ（allocation finger）
    /// 常に self.data..=self の範囲内
    ptr: Cell<NonNull<u8>>,

    /// すべてのチャンクで割り当てられた累積バイト数
    /// 空チャンクは 0、それ以外は current + prev の合計
    allocated_bytes: usize,
}
```

**メモリレイアウト**:
```
[================ データ領域 ================][ChunkFooter]
 ^                                           ^            ^
 data                                        ptr          self
 
リンクリスト: ChunkFooter.prev -> 前のチャンク -> ... -> 空チャンク (self-loop)
```

---

## データ構造

### 1. Vec<'a, T>

**ファイル**: `src/vec.rs`

Arena に割り当てられるベクタ実装。

```rust
pub struct Vec<'a, T> {
    // 内部実装
}

impl<'a, T> Vec<'a, T> {
    /// アリーナから新しい Vec を作成
    pub fn new_in(allocator: &'a Allocator) -> Self;
    
    /// 指定された容量で Vec を作成
    pub fn with_capacity_in(capacity: usize, allocator: &'a Allocator) -> Self;
    
    // ... その他の std::vec::Vec と同様のメソッド
}
```

**使用例**:
```rust
let allocator = Allocator::default();
let mut vec = Vec::new_in(&allocator);
vec.push(1);
vec.push(2);
vec.push(3);
```

### 2. Box<'a, T>

**ファイル**: `src/boxed.rs`

Arena に割り当てられるボックス実装。

```rust
pub struct Box<'a, T: ?Sized> {
    // 内部実装
}

impl<'a, T> Box<'a, T> {
    /// アリーナにボックスを割り当て
    pub fn new_in(value: T, allocator: &'a Allocator) -> Self;
}
```

### 3. HashMap<'a, K, V>

**ファイル**: `src/hash_map.rs`

Arena に割り当てられるハッシュマップ実装。

```rust
pub type HashMap<'a, K, V, S = RandomState> = hashbrown::HashMap<K, V, S, &'a Allocator>;

impl<'a, K, V> HashMap<'a, K, V> {
    pub fn new_in(allocator: &'a Allocator) -> Self;
    pub fn with_capacity_in(capacity: usize, allocator: &'a Allocator) -> Self;
}
```

### 4. HashSet<'a, T>

**ファイル**: `src/hash_set.rs`

Arena に割り当てられるハッシュセット実装（`HashMap` のラッパー）。

---

## API リファレンス

### Allocator::new()

**ファイル**: `src/allocator.rs` (行 236-263)

```rust
#[expect(clippy::inline_always)]
#[inline(always)]
pub fn new() -> Self {
    Self {
        bump: Bump::new(),
        #[cfg(all(feature = "track_allocations", not(feature = "disable_track_allocations")))]
        stats: AllocationStats::default(),
    }
}
```

**特徴**:
- 初期容量 0 で作成
- メモリは最初の割り当て時に遅延確保
- 推奨: 事前に必要量が分かる場合は `with_capacity` を使用

### Allocator::with_capacity()

**ファイル**: `src/allocator.rs` (行 265-275)

```rust
#[expect(clippy::inline_always)]
#[inline(always)]
pub fn with_capacity(capacity: usize) -> Self {
    Self {
        bump: Bump::with_capacity(capacity),
        #[cfg(all(feature = "track_allocations", not(feature = "disable_track_allocations")))]
        stats: AllocationStats::default(),
    }
}
```

### Allocator::alloc<T>()

**ファイル**: `src/allocator.rs` (行 277-298)

```rust
#[expect(clippy::inline_always)]
#[inline(always)]
pub fn alloc<T>(&self, val: T) -> &mut T {
    // コンパイル時チェック: Drop トレイトを実装した型は禁止
    const { assert!(!std::mem::needs_drop::<T>(), "Cannot allocate Drop type in arena") };

    #[cfg(all(feature = "track_allocations", not(feature = "disable_track_allocations")))]
    self.stats.record_allocation();

    self.bump.alloc(val)
}
```

**制約**:
- `T` は `Drop` トレイトを実装してはいけない（コンパイル時エラー）
- パニック: メモリ確保に失敗した場合

**インライン化の理由**:
- ホットパスであるため
- `Bump::alloc` が非常に小さい関数
- 呼び出しオーバーヘッドを完全に排除

### Allocator::alloc_str()

**ファイル**: `src/allocator.rs` (行 300-319)

```rust
#[expect(clippy::inline_always)]
#[inline(always)]
pub fn alloc_str<'alloc>(&'alloc self, src: &str) -> &'alloc str {
    #[cfg(all(feature = "track_allocations", not(feature = "disable_track_allocations")))]
    self.stats.record_allocation();

    self.bump.alloc_str(src)
}
```

### Allocator::alloc_slice_copy<T: Copy>()

**ファイル**: `src/allocator.rs` (行 321-339)

```rust
#[expect(clippy::inline_always)]
#[inline(always)]
pub fn alloc_slice_copy<T: Copy>(&self, src: &[T]) -> &mut [T] {
    #[cfg(all(feature = "track_allocations", not(feature = "disable_track_allocations")))]
    self.stats.record_allocation();

    self.bump.alloc_slice_copy(src)
}
```

### Allocator::reset()

**ファイル**: `src/allocator.rs` (行 400-416)

```rust
#[expect(clippy::inline_always)]
#[inline(always)]
pub fn reset(&mut self) {
    #[cfg(all(feature = "track_allocations", not(feature = "disable_track_allocations")))]
    self.stats.reset();

    self.bump.reset();
}
```

**動作**:
1. すべての割り当てを一括で解放（O(1)）
2. ポインタを先頭に戻す
3. 余分なチャンクをシステムアロケータに返却
4. `Drop` 実装は実行されない

### Allocator::capacity()

**ファイル**: `src/allocator.rs` (行 468-481)

```rust
#[expect(clippy::inline_always)]
#[inline(always)]
pub fn capacity(&self) -> usize {
    self.bump.allocated_bytes()
}
```

**返り値**: すべてのチャンクを含む総容量（バイト）

### Allocator::used_bytes()

**ファイル**: `src/allocator.rs` (行 483-562)

```rust
pub fn used_bytes(&self) -> usize {
    let mut bytes = 0;
    // SAFETY: chunks_iter が生きている間は割り当てが行われない
    let chunks_iter = unsafe { self.bump.iter_allocated_chunks_raw() };
    for (_, size) in chunks_iter {
        bytes += size;
    }
    bytes
}
```

**注意**: 以下を含む:
1. アライメントのためのパディングバイト
2. `Vec` などの余分な容量
3. ドロップされたオブジェクトの「デッドスペース」
4. 成長したコンテナの古い割り当て

---

## 高度な機能

### 1. AllocatorPool

**ファイル**: `src/pool/mod.rs` (行 31-107)

マルチスレッド環境でアロケータを再利用するためのプール。

#### 基本構造

```rust
pub struct AllocatorPool(AllocatorPoolInner);

enum AllocatorPoolInner {
    Standard(StandardAllocatorPool),
    #[cfg(all(feature = "fixed_size", target_pointer_width = "64", target_endian = "little"))]
    FixedSize(FixedSizeAllocatorPool),
}
```

#### StandardAllocatorPool

**ファイル**: `src/pool/standard.rs` (行 9-11)

```rust
pub struct StandardAllocatorPool {
    allocators: Mutex<Vec<Allocator>>,
}
```

**実装** (行 13-44):

```rust
impl StandardAllocatorPool {
    pub fn new(thread_count: usize) -> Self {
        let allocators = (0..thread_count).map(|_| Allocator::default()).collect();
        Self { allocators: Mutex::new(allocators) }
    }

    pub fn get(&self) -> Allocator {
        self.allocators.lock().unwrap().pop().unwrap_or_default()
    }

    pub unsafe fn add(&self, mut allocator: Allocator) {
        allocator.reset();
        self.allocators.lock().unwrap().push(allocator);
    }
}
```

#### AllocatorGuard

```rust
pub struct AllocatorGuard<'pool> {
    allocator: ManuallyDrop<Allocator>,
    pool: &'pool AllocatorPool,
}

impl<'pool> AllocatorGuard<'pool> {
    pub fn allocator(&self) -> &Allocator {
        &self.allocator
    }
}

impl Drop for AllocatorGuard<'_> {
    fn drop(&mut self) {
        // SAFETY: allocator は二度と使用されない
        let allocator = unsafe { ManuallyDrop::take(&mut self.allocator) };
        self.pool.add(allocator);
    }
}
```

**使用例**:
```rust
let pool = AllocatorPool::new(4); // 4スレッド用

// スレッド内で使用
let guard = pool.get();
let allocator = guard.allocator();
let value = allocator.alloc(42);
// guard がドロップされると自動的にプールに返却される
```

### 2. CloneIn トレイト

**ファイル**: `src/clone_in.rs`

Arena に値をクローンするためのトレイト。

```rust
pub trait CloneIn: Sized {
    fn clone_in(&self, allocator: &Allocator) -> Self;
}
```

### 3. TakeIn トレイト

**ファイル**: `src/take_in.rs`

値の所有権を移動して新しいアリーナに再配置するトレイト。

```rust
pub trait TakeIn: Sized {
    fn take_in(self, allocator: &Allocator) -> Self;
}
```

---

## パフォーマンス最適化

### 1. インライン化戦略

**すべての主要メソッドに `#[inline(always)]` を適用**:

```rust
#[expect(clippy::inline_always)]
#[inline(always)]
pub fn alloc<T>(&self, val: T) -> &mut T { ... }
```

**理由**:
- ホットパスであるため
- `Bump::alloc` 自体が非常に小さい
- 呼び出しオーバーヘッドを完全に排除
- コンパイラによる最適化を最大化

### 2. Drop 型の禁止

```rust
const { assert!(!std::mem::needs_drop::<T>(), "Cannot allocate Drop type in arena") }
```

**利点**:
- デストラクタ呼び出しのオーバーヘッドなし
- メモリリークを防ぐ
- コンパイル時に検出

### 3. Bump Pointer Allocation

**高速な理由**:
1. **単純**: ポインタのインクリメントだけ
2. **ロックフリー**: 並行性に優れる
3. **キャッシュフレンドリー**: 連続したメモリ配置
4. **一括解放**: O(1) で全メモリを解放

**動作フロー**:
```
初期状態:
[________________________]
 ^ptr

割り当て後:
[====データ====___________]
             ^ptr

複数割り当て後:
[====D1===][==D2==][==D3==]
                         ^ptr
```

### 4. アライメント処理

異なるアライメント要求に自動対応:

```rust
// 例: u8 の後に u64 を割り当て
allocator.alloc(1u8);  // 1 byte, align 1
allocator.alloc(2u8);  // 1 byte, align 1
allocator.alloc(3u64); // 8 bytes, align 8
// ↑ 自動的にパディングが挿入される

// used_bytes() = 16 (1 + 1 + 6 (padding) + 8)
```

---

## 使用例

### 基本的な使用

```rust
use oxc_allocator::Allocator;

let allocator = Allocator::default();

// オブジェクトの割り当て
let x = allocator.alloc([1u8; 20]);
assert_eq!(x, &[1u8; 20]);

// 文字列の割り当て
let hello = allocator.alloc_str("hello world");
assert_eq!(hello, "hello world");

// スライスの割り当て
let slice = allocator.alloc_slice_copy(&[1, 2, 3]);
assert_eq!(slice, &[1, 2, 3]);
```

### Vec の使用

```rust
use oxc_allocator::{Allocator, Vec};

let allocator = Allocator::default();
let mut vec = Vec::new_in(&allocator);

vec.push(1);
vec.push(2);
vec.push(3);

assert_eq!(vec.as_slice(), &[1, 2, 3]);
```

### HashMap の使用

```rust
use oxc_allocator::{Allocator, HashMap};

let allocator = Allocator::default();
let mut map = HashMap::new_in(&allocator);

map.insert("key1", 100);
map.insert("key2", 200);

assert_eq!(map.get("key1"), Some(&100));
```

### AST ノードの割り当て（実際の使用例）

```rust
use oxc_allocator::{Allocator, Box, Vec};
use oxc_ast::ast::*;

let allocator = Allocator::default();

// Expression を割り当て
let ident = allocator.alloc(IdentifierReference {
    span: SPAN,
    name: allocator.alloc_str("myVar"),
    reference_id: Cell::new(None),
});

// Vec でノードのリストを管理
let mut statements = Vec::new_in(&allocator);
statements.push(/* Statement */);
statements.push(/* Statement */);
```

### AllocatorPool の使用

```rust
use oxc_allocator::AllocatorPool;
use std::thread;

let pool = AllocatorPool::new(4); // 4スレッド用

let handles: Vec<_> = (0..4)
    .map(|i| {
        let pool = &pool;
        thread::spawn(move || {
            let guard = pool.get();
            let allocator = guard.allocator();
            
            // アロケータを使用
            let value = allocator.alloc(i * 100);
            println!("Thread {}: {}", i, value);
            
            // guard がドロップされると自動的にプールに返却
        })
    })
    .collect();

for handle in handles {
    handle.join().unwrap();
}
```

---

## まとめ

oxc の Arena Allocator は、AST やその他のパース結果を格納するために最適化された高性能なメモリアロケータです。

### 主要な特徴

1. **Bump pointer allocation**: 単純で超高速
2. **チャンクのリンクリスト**: 動的にメモリを拡張
3. **コンパイル時安全性**: Drop 型の禁止
4. **徹底したインライン化**: パフォーマンスを最大化
5. **豊富なデータ構造**: Vec, Box, HashMap, HashSet など
6. **AllocatorPool**: マルチスレッド対応

### ファイル位置まとめ

| コンポーネント | ファイル | 主要な行 |
|--------------|---------|---------|
| Allocator 構造体 | `src/allocator.rs` | 222-227 |
| alloc メソッド | `src/allocator.rs` | 277-298 |
| reset メソッド | `src/allocator.rs` | 400-416 |
| ChunkFooter | `src/from_raw_parts.rs` | 354-375 |
| AllocatorPool | `src/pool/mod.rs` | 31-107 |
| StandardAllocatorPool | `src/pool/standard.rs` | 9-44 |
| Vec | `src/vec.rs` | - |
| Box | `src/boxed.rs` | - |
| HashMap | `src/hash_map.rs` | - |

この設計により、oxc はパース処理において非常に高いパフォーマンスを実現しています。


---

## Metadata

Last Updated: 2025-10-09T12:51:10.119Z
Goal: oxc の arena allocator の完全な実装詳細と位置情報を提供する
Query: oxc allocator implementation details file structure module composition
Summary: oxc は bumpalo ベースの arena allocator を使用し、oxc_allocator クレートで実装。主要ファイル: allocator.rs (Allocator 構造体、alloc メソッド), from_raw_parts.rs (ChunkFooter), pool/mod.rs (AllocatorPool), vec.rs/boxed.rs/hash_map.rs (データ構造)。全メソッドに inline(always) を適用し、Drop 型を禁止し、バンプポインタ割り当てで高速化。
Tags: oxc, arena-allocator, implementation, file-structure, rust, performance, bumpalo, detailed-analysis
CreatedBy: agent
CreatedAt: 2025-10-09T12:51:10.119Z