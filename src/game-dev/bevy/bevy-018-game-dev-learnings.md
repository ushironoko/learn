# Bevy 0.18 ゲーム開発で得た知見

## 概要

Bevy 0.18 でローグライクダンジョンゲームを開発する中で得た、カメラ生成タイミング・API 変更・ECS 設計パターン・テスト手法に関する知見。

## 背景・きっかけ

Phase 5（Menu/GameOver/Ending 画面・レアリティシステム・アイテム時間転送）を実装する過程で、Bevy 0.18 固有の問題やECSアーキテクチャのベストプラクティスに直面した。

## 学んだこと

### カメラが存在しないと UI も描画されない

Menu 画面を実装した際、起動後に真っ黒画面のまま進まない問題が発生。原因は `Camera2d` が `OnEnter(Playing)` でしか生成されず、`Menu` 状態ではカメラが存在しなかったこと。

Bevy では **カメラが存在しなければ UI ノードも一切描画されない**。ゲーム全体で UI を表示する可能性がある場合、カメラは最も早い段階（`Loading` 等）で生成する必要がある。

```rust
// NG: Playing 以外の状態で UI が表示されない
app.add_systems(OnEnter(GameState::Playing), spawn_camera);

// OK: 全状態でカメラが利用可能
app.add_systems(OnEnter(GameState::Loading), spawn_camera);
```

### Bevy 0.18 の API 変更: ChildBuilder → ChildSpawnerCommands

Bevy 0.18 では `with_children` のクロージャ引数の型が `ChildBuilder` から `ChildSpawnerCommands` に変更された。`with_children` のクロージャ内で直接使う分には型推論が効くため問題ないが、ヘルパー関数に引数として渡す場合は明示的な型指定が必要。

```rust
// Bevy 0.17 以前
fn spawn_button(parent: &mut ChildBuilder, text: &str) { ... }

// Bevy 0.18
fn spawn_button(parent: &mut ChildSpawnerCommands, text: &str) { ... }
```

### Changed<Interaction> によるボタン検出

Bevy UI のボタンクリック検出には `Changed<Interaction>` フィルタを使うことで、毎フレーム全ボタンをチェックする無駄を回避できる。

```rust
fn menu_interaction(
    query: Query<&Interaction, (Changed<Interaction>, With<StartButton>)>,
    mut next_state: ResMut<NextState<GameState>>,
) {
    for interaction in &query {
        if *interaction == Interaction::Pressed {
            next_state.set(GameState::FloorTransition);
        }
    }
}
```

### OnEnter/OnExit による UI ライフサイクル管理

各画面に Root マーカーコンポーネントを付け、`OnEnter` で生成・`OnExit` で despawn する一貫したパターン。

```rust
// 生成: OnEnter で Root ごとスポーン
app.add_systems(OnEnter(GameState::Menu), spawn_menu);
// 破棄: OnExit で Root を despawn（子も自動削除）
app.add_systems(OnExit(GameState::Menu), cleanup_menu);

fn cleanup_menu(mut commands: Commands, query: Query<Entity, With<MenuRoot>>) {
    for entity in &query {
        commands.entity(entity).despawn();
    }
}
```

注意点として、HUD の cleanup を `OnExit(Playing)` に置くと、`FloorTransition` や `InventoryOpen` への遷移でも消えてしまう。代わりに `OnEnter(GameOver)` + `OnEnter(Ending)` のように **消したい先の状態の OnEnter** に登録する。

### 純粋関数の分離によるテスト容易性

ゲームロジック（ダメージ計算、レアリティ判定、装備比較等）を Bevy の System から切り離し、純粋関数として定義する。ECS の World を構築せずにユニットテストが書ける。

```rust
// 純粋関数: Bevy への依存なし
pub fn compute_stat_value(base: u32, rarity: Rarity, level: u32, scaling: f32) -> u32 {
    let mult = rarity_multiplier(rarity);
    let level_mult = 1.0 + level as f32 * scaling;
    (base as f32 * mult * level_mult) as u32
}

// System 側は純粋関数を呼ぶだけ
fn update_player_stats(
    mut query: Query<(&mut Attack, &mut Defense), With<Player>>,
    player_state: Res<PlayerState>,
    config: Res<GameConfig>,
) {
    let Ok((mut attack, mut defense)) = query.single_mut() else { return };
    attack.0 = effective_attack(config.player.attack, &player_state.equipment, &config.item);
    defense.0 = effective_defense(config.player.defense, &player_state.equipment, &config.item);
}

// テスト: World 不要
#[test]
fn test_compute_stat_value() {
    assert_eq!(compute_stat_value(5, Rarity::Rare, 10, 0.1), 20);
}
```

## ポイント

- Bevy ではカメラなしでは何も描画されない（UI 含む）。起動直後から UI を出すなら Loading でカメラ生成
- Bevy 0.18 で `ChildBuilder` → `ChildSpawnerCommands` に型名変更。ヘルパー関数の引数型に注意
- `Changed<Interaction>` フィルタでボタン検出を効率化
- HUD の cleanup は `OnExit(Playing)` ではなく、消したい状態の `OnEnter` に登録
- ゲームロジックを純粋関数に分離すれば、ECS の World 構築なしでテスト可能

## 参考

- [Bevy 0.18 Examples - UI Grid](https://github.com/bevyengine/bevy/blob/main/examples/ui/grid.rs)
