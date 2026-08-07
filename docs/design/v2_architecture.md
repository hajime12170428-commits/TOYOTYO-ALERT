# TOYOCHO ALERT Ver2.0 アーキテクチャ設計書

- 作成日：2026-08-06
- 状態：設計案（実装前）
- 方針：現行コードに縛られず、ゼロベースで設計する
- 要件：保守性最優先／高速／商用レベル／数万人／複数路線／複数ユーザー／
  通知速度最優先／AI追加可能／PWA／スマホ最適化

---

## 0. 現行（Ver1）の構造的な限界

| 限界 | 理由 | Ver2での解 |
|---|---|---|
| 1人しか使えない | 監視状態が`alarm_data`というグローバル辞書1つ。全利用者が同じ状態を共有 | 購読（Subscription）を利用者ごとの実体にする |
| 利用者数だけ上流APIを叩く | 利用者1人＝スレッド1本＝2秒ごとのリクエスト1本。1万人なら毎秒5,000リクエスト | **路線ごとに1本だけ取り込み、全購読に配る**（O(利用者)→O(路線)） |
| 再起動で二重通知 | 通知済み集合がメモリ上のset | 冪等な重複排除キー（Redis・期限付き） |
| 通知が遅い・届かない | 画面を開いている間のポーリングのみ。閉じたら鳴らない | Web Push（閉じていても届く）＋SSE（開いている時は即時） |
| 1路線固定 | URLに東西線がハードコード | 路線を設定データにし、取り込みアダプターを差し替え可能に |
| 履歴がCSV | 同時書き込みで壊れる・検索できない | PostgreSQL（月単位パーティション） |
| テストできない | 判定ロジックがHTTP・時間・グローバル変数と絡み合っている | 純粋な判定層（外部依存ゼロ）に分離 |

---

## 1. ディレクトリ構成

```
toyocho-alert/
├─ apps/
│  ├─ api/                     # 利用者向けHTTP＋リアルタイム配信
│  │  └─ src/toyocho/
│  │     ├─ domain/            # ★外部依存ゼロ（ここが資産）
│  │     │  ├─ models.py       # Line, Station, TrainSnapshot, Subscription
│  │     │  ├─ events.py       # TrainArrived / TrainApproaching / DelayChanged
│  │     │  ├─ matching.py     # 購読と列車の一致判定（純粋関数）
│  │     │  ├─ schedule.py     # 有効時間帯・おやすみ時間の判定
│  │     │  └─ dedupe.py       # 重複排除キーの決め方
│  │     ├─ application/       # ユースケース（手順の組み立て）
│  │     │  ├─ create_subscription.py
│  │     │  ├─ evaluate_events.py
│  │     │  ├─ deliver_alert.py
│  │     │  └─ ports.py        # 外部への窓口（抽象）
│  │     ├─ adapters/          # 差し替え可能な外部接続
│  │     │  ├─ feeds/          # nkth / ODPT / モック
│  │     │  ├─ push/           # WebPush / 将来APNs・FCM
│  │     │  ├─ repository/     # PostgreSQL
│  │     │  ├─ cache/          # Redis（索引・重複排除・ロック）
│  │     │  └─ bus/            # Redis Pub/Sub
│  │     ├─ interfaces/
│  │     │  ├─ http/           # FastAPI ルーター（v1）
│  │     │  └─ realtime/       # SSE
│  │     └─ platform/          # 設定・ログ・計測・エラー
│  ├─ ingestor/                # 路線ごとの取り込みワーカー
│  │  └─ src/toyocho_ingest/
│  │     ├─ poller.py          # 適応ポーリング＋条件付きGET
│  │     ├─ differ.py          # 前回との差分→イベント化
│  │     ├─ leader.py          # 路線ごとの担当者決め（Redisロック）
│  │     └─ publisher.py       # イベントをPub/Subへ
│  └─ web/                     # PWA（Vite + React + TypeScript）
│     ├─ src/
│     │  ├─ features/          # 機能単位（home / subscribe / history）
│     │  ├─ shared/            # UI部品・hooks・api client
│     │  └─ pwa/               # service worker・push受信・音・振動
│     └─ public/manifest.json
├─ packages/
│  └─ contracts/               # OpenAPIから自動生成した型（サーバーと画面で共有）
├─ infra/                      # Docker・デプロイ定義・監視
├─ docs/design/                # 設計書（本書）
└─ tests/
   ├─ unit/                    # domain（外部なし・数千件を一瞬で）
   ├─ integration/             # DB・Redis込み
   └─ e2e/                     # 取り込み→通知の通し
```

**依存の向きは一方通行**：`interfaces → application → domain`、`adapters → application`。
domainは何にも依存しない。この一本の規則が保守性の核。

---

## 2. クラス設計

### 2.1 domain（純粋・テスト容易）

```python
# models.py
@dataclass(frozen=True)
class TrainSnapshot:
    line_id: str
    train_number: str
    destination: str
    direction: str            # 上り/下り
    current_stations: frozenset[str]
    delay_minutes: int
    observed_at: datetime

@dataclass(frozen=True)
class Subscription:            # 集約ルート
    id: str
    user_id: str
    line_id: str
    station_id: str
    direction: str | None      # None = 両方向
    destination: str | None    # None = すべての行先
    train_number: str | None   # None = すべての列車
    lead_time_sec: int         # 何秒前に鳴らすか（AI予測で使う）
    schedule: ActiveSchedule   # 曜日・時間帯・おやすみ時間
    active: bool

# events.py（取り込みが生む唯一の出力）
class TrainArrived(TrainEvent):     ...
class TrainApproaching(TrainEvent): ...   # AI予測で発火
class DelayChanged(TrainEvent):     ...
```

```python
# matching.py — 純粋関数。ここに全判定が集まる
def match(event: TrainEvent, subs: Sequence[Subscription], now: datetime) -> list[Match]:
    """一致した購読を返す。外部I/Oなし・時刻は引数で受け取る（テスト可能にするため）"""
```

```python
# dedupe.py
def dedupe_key(sub: Subscription, event: TrainEvent) -> str:
    return f"alert:{sub.id}:{event.train_number}:{event.station_id}"
```

### 2.2 application（手順とポート）

```python
class FeedPort(Protocol):        # 上流データ
    async def fetch(self, line: Line) -> list[TrainSnapshot]: ...

class PushPort(Protocol):        # 通知の出口
    async def send(self, device: Device, alert: Alert) -> DeliveryResult: ...

class SubscriptionIndex:         # ★数万人を支える索引
    """(line_id, station_id) → 購読リスト をメモリに保持。
    参照はO(1)。更新はPub/Subで各インスタンスへ通知して差分反映。"""
    def find(self, line_id: str, station_id: str) -> list[Subscription]: ...

class AlertPolicy(Protocol):     # ★AIを差し込む口
    def decide(self, m: Match, ctx: Context) -> AlertDecision: ...

class EvaluateEvents:            # 取り込み→通知の中核ユースケース
    async def handle(self, events: list[TrainEvent]) -> None:
        for e in events:
            for sub in self.index.find(e.line_id, e.station_id):
                m = match(e, [sub], now())
                if not m: continue
                if not await self.dedupe.acquire(dedupe_key(sub, e), ttl=900):
                    continue                       # 既に鳴らした
                decision = self.policy.decide(m[0], ctx)   # ルール or AI
                if decision.should_fire:
                    await self.dispatcher.fan_out(sub, decision)
```

### 2.3 ingestor

```python
class LinePoller:        # 路線1本を担当。適応間隔・ETag・購読ゼロなら休止
class SnapshotDiffer:    # 前回スナップショットと比較してイベント化（状態は明示的に保持）
class LineLeader:        # Redisロックで「この路線は自分が担当」を宣言（多重取り込み防止）
```

---

## 3. DB設計（PostgreSQL）

```sql
users(id PK, created_at, email NULL, plan)                 -- 匿名で開始可能
devices(id PK, user_id FK, endpoint, p256dh, auth,
        platform, last_seen_at, revoked_at)                -- 1人=複数端末
lines(id PK, name, feed_key, operator, active)
stations(id PK, line_id FK, name, kana, order_no)

subscriptions(id PK, user_id FK, line_id FK, station_id FK,
              direction, destination, train_number,
              lead_time_sec, schedule JSONB, active, created_at)

alerts(id, subscription_id, user_id, train_number, station_id,
       detected_at, fired_at, delivered_at, acked_at,
       latency_ms, policy)                                 -- 月単位パーティション

delivery_attempts(alert_id, device_id, channel, status, error, attempted_at)
train_observations(line_id, train_number, station_id, observed_at,
                   delay_minutes)                          -- AI学習の材料。月パーティション
```

**要となる索引**

```sql
CREATE INDEX ON subscriptions (line_id, station_id) WHERE active;  -- 最頻経路
CREATE INDEX ON alerts (user_id, fired_at DESC);                   -- 履歴表示
CREATE INDEX ON devices (user_id) WHERE revoked_at IS NULL;
```

**Redis**（速度のためだけに使う。失っても再構築できる）

| 用途 | キー | 期限 |
|---|---|---|
| 重複排除 | `alert:{sub}:{train}:{station}` | 15分 |
| 路線の担当者ロック | `lock:line:{id}` | 30秒（更新し続ける） |
| 索引の更新通知 | `sub:changed` (Pub/Sub) | — |
| イベント配信 | `events:{line_id}` (Pub/Sub) | — |

---

## 4. API設計（REST + SSE、`/v1`）

| 種別 | 経路 | 用途 |
|---|---|---|
| 認証 | `POST /v1/auth/anonymous` | 端末トークン発行（登録不要で即使える） |
| マスタ | `GET /v1/lines` / `GET /v1/lines/{id}/stations` | ETagで長期キャッシュ |
| 購読 | `POST/GET/PATCH/DELETE /v1/subscriptions` | 見張りの作成・停止 |
| 端末 | `POST /v1/devices/push` | Web Push購読の登録 |
| 履歴 | `GET /v1/alerts?limit=&cursor=` | カーソル方式 |
| 確認 | `POST /v1/alerts/{id}/ack` | アラーム停止・遅延計測の終点 |
| 実時間 | `GET /v1/stream` (SSE) | 前面表示中の即時配信 |
| 運用 | `GET /healthz` `/readyz` `/metrics` | 死活・監視 |

- 書き込みは`Idempotency-Key`必須（通信途絶での二重登録を防ぐ）
- 取り込みワーカー→API間は**HTTPではなくRedis Pub/Sub**（往復を挟まない＝速い）

---

## 5. UI構成（PWA・スマホ最適化）

画面は3つだけ。片手・親指の届く下部に操作を置く。

1. **ホーム**：見張り中カード（路線・駅・行先を大きく）／即停止ボタン
2. **アラート（全画面）**：列車番号・行先・到着表示、大きな「止める」、音＋振動＋画面点灯
3. **設定・履歴**：路線→駅→方面 の3タップで購読作成。履歴は時系列

スマホの現実に対する設計上の手当て：

| 制約 | 対処 |
|---|---|
| iOSはホーム画面追加後でないとWeb Pushが使えない | 初回に「ホーム画面に追加」を案内するステップを置く |
| 音は利用者の操作なしに鳴らせない | 初回に「音を許可」ボタンで無音を1回再生して解錠 |
| 画面が消えると処理が止まる | 通知はWeb Push（OS側）に任せる。SSEは前面時の高速化用 |
| 電波が切れる | Service Workerで画面と設定を先読み保存。復帰時にSSE自動再接続 |

---

## 6. 通知構成（速度最優先）

**状態で経路を変える二層構成**

```
取り込み(1路線1本) ─差分検出→ イベント ─Pub/Sub→ API群
                                        ├─ 前面利用者 → SSE      （即時・音/振動）
                                        └─ 背面/終了  → Web Push（OS通知）
                                                          ↓ 未確認が続けば再送
```

**遅延の内訳（正直な見積り）**

| 区間 | 時間 | 短縮の可否 |
|---|---|---|
| 上流データの更新間隔 | 0〜15秒 | **不可**（ここが支配的） |
| 取り込みの検知 | ≦1秒 | 適応ポーリング＋条件付きGET |
| 一致判定 | 5ミリ秒未満 | メモリ索引 |
| 配信（前面／背面） | 0.1秒／0.5〜3秒 | SSE常時接続 |

→ **検知から手元までは1秒以内**にできる。しかし全体の速さは上流の更新間隔で決まる。
**これを超える唯一の道が「予測して先に鳴らす」**（7章のAI）。

**計測（速いと言うために必須）**：`detected_at → delivered_at`をアラートごとに記録し、
p50/p95を常時監視。遅くなったら気づける状態を作る。

---

## 7. 将来追加できる機能

| 優先 | 機能 | 差し込み場所 |
|---|---|---|
| ★ | **AI到着予測**（前駅の通過時刻から到達を予測し、上流更新を待たずに鳴らす） | `AlertPolicy`を差し替えるだけ |
| ★ | 遅延予測・運転見合わせの早期検知 | `TrainEvent`の派生を追加 |
| ○ | 自然言語で購読設定（「平日の朝、木場に西船橋行きが来たら」） | 入力→Subscriptionへの変換層を追加 |
| ○ | 複数事業者（JR・私鉄）対応 | `FeedPort`の実装を追加するだけ |
| ○ | 家族・グループ共有通知 | Subscriptionに共有先を追加 |
| △ | 混雑予測、Apple Watch／ウィジェット、有料プラン | 既存構造のまま拡張可 |

**AIを足せる構造の実体**：判定は`AlertPolicy`という1つの窓口に閉じてある。
ルールベースの実装をAIモデルの実装に差し替えても、取り込み・配信・画面は一切変わらない。
学習用データは`train_observations`に最初から貯め続ける。

---

## 8. なぜこの設計なのか

1. **取り込みを利用者数から切り離した**
   Ver1の致命傷は「利用者1人＝上流ポーリング1本」。1万人で毎秒5,000リクエストとなり、
   規模拡大の前に上流から遮断される。**路線ごとに1本だけ取り込み、全購読へ配る**ことで、
   上流負荷は利用者数と無関係（O(路線)）になる。数万人対応の本体はこの一点。

2. **domain層を外部依存ゼロにした（保守性最優先の実体）**
   判定ロジックがHTTP・時刻・グローバル変数と絡むと、テストも変更もできない。
   純粋関数に切り出せば、数千通りの条件を一瞬で自動テストでき、
   路線が増えても通知手段が変わっても**この層は書き換えなくてよい**。

3. **状態ではなく「差分イベント」で考える**
   「駅にいる列車の一覧」を毎回見て鳴らすと、居続ける限り鳴り続ける。
   前回との差分を`TrainArrived`イベントに変換すれば、二重通知は設計上起きない。
   加えてRedisの期限付きキーで冪等にし、**再起動しても多重起動しても鳴り直さない**。

4. **通知を二層にした（速さと確実性は別物）**
   常時接続（SSE）は速いが、画面を閉じれば切れる。Web Pushは確実だが数秒かかる。
   どちらか一方では商用に足りない。**前面はSSE・背面はPushの併用**が唯一の解。

5. **AIを「後から差し込む」前提で口を空けた**
   AI機能は目的ではなく手段。通知速度の限界（上流の更新間隔）を破れるのは予測だけなので、
   `AlertPolicy`という差し替え点と、学習データの蓄積だけを先に用意しておく。

6. **作らないものを決めた（これも設計判断）**
   マイクロサービス・Kubernetes・イベントソーシングは**採用しない**。
   実測上、取り込み1プロセス＋API数プロセス＋PostgreSQL＋Redisで数万人に足りる
   （購読10万件でも索引は約20MB、判定はミリ秒未満。同時接続は前面利用者のみで全体の数%）。
   保守する人数に対して過剰な部品は、それ自体が最大の保守コストになる。
