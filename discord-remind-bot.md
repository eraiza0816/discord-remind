# Discord Remind Bot ドメイン設計書

## 1. はじめに

*   **プロジェクトの目的**: Slackのremind機能と同等の機能を持つDiscordボットを開発する。
*   **ドキュメントの目的**: このドキュメントは、Discord Remind Botのドメイン知識、設計、実装方針をドメイン駆動設計（DDD）の観点から記述し、関係者間の共通理解を形成することを目的とする。
*   **ユビキタス言語 (Ubiquitous Language)**:
    *   `Reminder`: ユーザーが設定するリマインド情報全体。ドメインの中心的な概念であり、集約ルート(Aggregate Root)。
    *   `Target`: リマインドの通知先。`User` または `Channel` のいずれか。
    *   `User`: Discordユーザー。リマインド設定者(Author)または通知先(Target)。
    *   `Channel`: Discordテキストチャンネル。通知先(Target)。
    *   `TriggerTime`: リマインドが実行されるべき日時 (タイムゾーン情報を含む)。
    *   `Message`: リマインド時に通知される内容。
    *   `RecurrenceRule`: 繰り返しのルール (例: 毎日、毎週月曜)。iCalendar(RFC 5545)形式に近い文字列で表現。
    *   `Schedule`: リマインドを特定の`TriggerTime`に実行するためのタスクスケジューラへの登録情報。
    *   `Notification`: スケジュールされた時刻に`Target`へ`Message`を送信する行為。
    *   `ReminderID`: 各`Reminder`を一意に識別するID。

## 2. 境界づけられたコンテキスト (Bounded Context)

*   **リマインダー管理コンテキスト (Reminder Management Context)**:
    *   **責務**: `Reminder`のライフサイクル（作成、読み取り、削除）の管理、`TriggerTime`に基づく`Schedule`の管理、および`Notification`のトリガー。ドメインロジックの中核を担う。
    *   **主要な関心事**: 正確な時刻に、正しい`Target`へ、指定された`Message`でリマインドを実行すること。繰り返しルールの解釈と次回の`TriggerTime`計算（※将来的な実装）。
*   **コンテキストマップ**:
    ```mermaid
    graph TD
        subgraph "外部システム"
            DiscordAPI["Discord API"]
            TaskScheduler["タスクスケジューラ (apscheduler)"]
        end

        subgraph "リマインダー管理コンテキスト"
            direction LR
            subgraph "アプリケーション層"
                AppService["アプリケーションサービス\n(Set/List/Delete Reminder)"] -- "ドメインモデル操作" --> DomainModel
            end
            subgraph "ドメイン層"
                DomainModel("ドメインモデル\n(Reminder Aggregate, etc.)") -- "永続化" --> ReminderRepo["Reminderリポジトリ"]
                DomainModel -- "イベント発行" --> DomainEvents["ドメインイベント\n(ReminderScheduled, etc.)"]
            end
            subgraph "インフラストラクチャ層"
                 ReminderRepo -- "DBアクセス" --> Database["データベース (SQLite)"]
                 SchedulerAdapter["スケジューラアダプタ"] -- "スケジュール登録/解除" --> TaskScheduler
                 DiscordNotifier["Discord通知アダプタ"] -- "メッセージ送信" --> DiscordAPI
            end
        end

        UserInterface["ユーザーインターフェース\n(Discord スラッシュコマンド)"] -- "コマンド実行要求" --> AppService
        TaskScheduler -- "時刻到来・トリガー" --> SchedulerAdapter
        SchedulerAdapter -- "リマインド実行指示" --> AppService  // または直接ドメインサービス/通知アダプタを呼ぶ場合も
        AppService -- "通知指示" --> DiscordNotifier // AppService経由の場合

        style DiscordAPI fill:#f9f,stroke:#333,stroke-width:2px
        style TaskScheduler fill:#f9f,stroke:#333,stroke-width:2px
        style UserInterface fill:#ccf,stroke:#333,stroke-width:2px
    end
    ```
    *   **リマインダー管理コンテキスト**: ボットの中核機能。
    *   **ユーザーインターフェース**: Discordのスラッシュコマンドを通じてユーザーからの入力を受け付け、アプリケーションサービスを呼び出す。
    *   **Discord API**: Discordとの通信（メッセージ送信、ユーザー/チャンネル情報取得）を行う外部システム。通知アダプタがこのAPIと連携する。
    *   **タスクスケジューラ**: `apscheduler`ライブラリ。指定時刻に処理を実行する外部システム。スケジューラアダプタがこれと連携する。

## 3. ドメインモデル (Domain Model)

*   **集約 (Aggregate): Reminder**
    *   **集約ルート (Aggregate Root)**: `Reminder`
        *   `id`: `ReminderID` (一意な識別子)
        *   `author_id`: `UserID` (設定者のID)
        *   `guild_id`: `GuildID` (設定されたサーバーのID)
    *   **含まれる要素**:
        *   `target`: `Target` (値オブジェクト: `UserTarget` または `ChannelTarget`)
            *   `type`: 'user' | 'channel'
            *   `id`: `UserID` | `ChannelID`
        *   `message`: `Message` (値オブジェクト)
        *   `trigger_time`: `TriggerTime` (値オブジェクト: aware datetime)
        *   `recurrence`: `Recurrence` (値オブジェクト)
            *   `is_recurring`: boolean
            *   `rule`: `RecurrenceRule` (値オブジェクト, 例: "FREQ=DAILY;BYHOUR=10;BYMINUTE=00")
    *   **不変条件 (Invariants)**:
        *   `Reminder` は必ず `Target`, `Message`, `TriggerTime` を持つ。
        *   `TriggerTime` は常に未来の日時である必要がある（設定時）。
        *   `RecurrenceRule` は `is_recurring` が true の場合にのみ意味を持つ。
*   **ドメインモデル図 (概念)**:
    ```mermaid
    classDiagram
        class Reminder {
            +ReminderID id
            +UserID author_id
            +GuildID guild_id
            +Target target
            +Message message
            +TriggerTime trigger_time
            +Recurrence recurrence
            +schedule(SchedulerAdapter)
            +cancel(SchedulerAdapter)
            +markAsSent()
            +calculateNextTriggerTime()*
        }
        class Target {
            <<ValueObject>>
            +string type ('user' | 'channel')
            +string id (UserID | ChannelID)
        }
        class Message {
            <<ValueObject>>
            +string content
        }
        class TriggerTime {
            <<ValueObject>>
            +datetime value (aware)
        }
        class Recurrence {
            <<ValueObject>>
            +bool is_recurring
            +RecurrenceRule rule
        }
        class RecurrenceRule {
            <<ValueObject>>
            +string value (e.g., "FREQ=DAILY;...")
        }
        Reminder *-- Target
        Reminder *-- Message
        Reminder *-- TriggerTime
        Reminder *-- Recurrence
        Recurrence *-- RecurrenceRule

        class ReminderRepository {
            <<Interface>>
            +save(Reminder)
            +findById(ReminderID) Reminder
            +findByUser(UserID) List~Reminder~
            +delete(ReminderID)
        }
        class SchedulerAdapter {
            <<Interface>>
            +scheduleReminder(Reminder) JobID
            +cancelReminder(JobID)
        }
        class DomainEvent {
            <<Interface>>
        }
        class ReminderScheduled {
            <<DomainEvent>>
            +ReminderID reminderId
            +datetime scheduledTime
        }
        class ReminderSent {
            <<DomainEvent>>
            +ReminderID reminderId
            +Target target
        }
        class ReminderDeleted {
            <<DomainEvent>>
            +ReminderID reminderId
        }

    ```
    *注意: 上記クラス図は概念的なものであり、実際の実装（`bot.py`）とは異なる場合があります。特に振る舞い（メソッド）は現状では`Reminder`オブジェクトに集約されていません。*
*   **リポジトリ (Repository)**:
    *   `ReminderRepository`: `Reminder`集約の永続化を担当するインターフェース。現在の実装では、各コマンド関数内で直接SQLiteにアクセスしている部分がこの責務を担っている。将来的にはリポジトリパターンを導入し、永続化ロジックを分離することが望ましい。
*   **ドメインイベント (Domain Event)**:
    *   `ReminderScheduled`: リマインダーが正常にスケジュールされた時に発行されるイベント。
    *   `ReminderSent`: リマインダーが正常に送信された時に発行されるイベント。
    *   `ReminderDeleted`: リマインダーが削除された時に発行されるイベント。
    *   *現状の実装ではドメインイベントは明示的に発行されていません。ロギングがその代わりを果たしています。*

## 4. アプリケーション層 (Application Layer)

*   **ユースケース (Use Cases)**:
    *   **リマインドを設定する**: ユーザーが指定した`Target`, `Time`, `Message` に基づき、新しい`Reminder`を作成し、永続化し、スケジュールする。
    *   **リマインド一覧を表示する**: ユーザーが設定した未実行または繰り返しの`Reminder`の一覧を取得し、表示する。
    *   **リマインドを削除する**: ユーザーが指定した`ReminderID`に基づき、`Reminder`を削除し、スケジュールもキャンセルする。
*   **アプリケーションサービス (Application Services)**:
    *   現在の実装では、各スラッシュコマンドのコールバック関数 (`slash_set_reminder`, `slash_list_reminders`, `slash_delete_reminder`) がアプリケーションサービスの役割を担っている。これらの関数は、入力（インタラクション）を受け取り、ドメインモデル（現状ではDB直接操作と`parse_time_string`）を操作し、結果をユーザーに返す。
*   **コマンド仕様 (Command Interface)**:
    *   `/remind set target:<target> time:<time> message:<message>`
        *   `<target>`: `@me`, `#channel-name`, ユーザーメンション, チャンネルメンション (文字列)
        *   `<time>`: 時刻表現 (文字列, 例: `15:30`, `in 1 hour`, `in 30 min`, `in 10 s`, `tomorrow at 9:00`, `every monday at 10:00`)
        *   `<message>`: リマインド内容 (文字列)
    *   `/remind list`
    *   `/remind delete reminder_id:<id>`
        *   `<id>`: 削除するリマインドのID (数値)
    *   `/remind help`

## 5. インフラストラクチャ層 (Infrastructure Layer)

*   **アーキテクチャ概要**: (コンテキストマップ参照)
*   **使用技術スタック**:
    *   プログラミング言語: Python 3.13+
    *   Discordライブラリ: `discord.py`
    *   タスクスケジューリングライブラリ: `apscheduler`
    *   日付/時刻パース支援: `python-dateutil`
    *   データベース: SQLite
    *   環境変数管理: `python-dotenv`
    *   パッケージ管理: `uv`
    *   コンテナ技術: Docker Compose
*   **データベース設計 (Data Model)**:
    *   `reminders` テーブル: `Reminder`集約の永続化表現。
        *   `id`: INTEGER PRIMARY KEY AUTOINCREMENT (`ReminderID`)
        *   `user_id`: TEXT (設定者のDiscordユーザーID)
        *   `guild_id`: TEXT (サーバーID)
        *   `channel_id`: TEXT (コマンド実行チャンネルID)
        *   `target_type`: TEXT ('user' or 'channel') (`Target.type`)
        *   `target_id`: TEXT (通知先ユーザー/チャンネルID) (`Target.id`)
        *   `message`: TEXT (`Message.content`)
        *   `trigger_time`: DATETIME (次回リマインド実行日時, JST基準のNaive文字列 'YYYY-MM-DD HH:MM:SS') (`TriggerTime.value`)
        *   `is_recurring`: BOOLEAN (`Recurrence.is_recurring`)
        *   `recurrence_rule`: TEXT (iCalendar風ルール文字列) (`RecurrenceRule.value`)
        *   `created_at`: DATETIME (作成日時)
*   **タスクスケジューリング**:
    *   `apscheduler.schedulers.asyncio.AsyncIOScheduler` を使用。
    *   単発リマインドは `'date'` トリガー、繰り返しリマインドは `CronTrigger` を使用して `send_reminder` 関数をスケジュール。
    *   タイムゾーンは `Asia/Tokyo` に設定。
*   **開発・実行環境**:
    *   `uv` でパッケージを管理 (`requirements.txt`)。
    *   `Dockerfile` と `docker-compose.yml` を使用してコンテナ環境で実行。
    *   Discord Bot Tokenは `.env` ファイルで管理。

## 6. 処理フロー概要

*   **リマインド設定時 (`/remind set`)**:
    1.  Interactionを受け取る。
    2.  `target` 文字列を解析し、`target_type`, `target_id` を決定。
    3.  `time` 文字列を `parse_time_string` で解析し、`trigger_datetime`, `is_recurring`, `recurrence_rule` を取得。
    4.  入力値と解析結果を検証（過去時刻でないか、など）。
    5.  `Reminder` 情報を `reminders` テーブルに保存 (`trigger_time` は 'YYYY-MM-DD HH:MM:SS' 形式)。
    6.  `apscheduler` に `send_reminder` ジョブを登録 (`date` または `CronTrigger`)。
    7.  結果をInteractionの応答として送信。
*   **リマインド実行時 (`send_reminder` ジョブ実行)**:
    1.  `apscheduler` が指定時刻に `send_reminder(reminder_id)` を実行。
    2.  DBから `reminder_id` に対応する `Reminder` 情報を取得。
    3.  `target_type`, `target_id` に基づき、Discord API を介して通知先 (`User` または `Channel`) を特定。
    4.  特定した `Target` に `Message` を送信。
    5.  `is_recurring` が false の場合、DBから `Reminder` 情報を削除。
    6.  `is_recurring` が true の場合、**現状では何もしない** (※将来的に次回のスケジュール更新処理が必要)。
*   **一覧表示時 (`/remind list`)**:
    1.  Interactionを受け取る。
    2.  実行ユーザーIDとサーバーIDに基づき、DBから有効な `Reminder` の一覧を取得。
    3.  取得した情報を整形し、EmbedとしてInteractionの応答（ephemeral）で送信。
*   **削除時 (`/remind delete`)**:
    1.  Interactionを受け取る。
    2.  指定された `reminder_id` と実行ユーザーIDに基づき、DBから削除対象の `Reminder` を特定。
    3.  対象が見つかれば、DBから削除。
    4.  `apscheduler` から対応するジョブを削除 (`scheduler.remove_job`)。
    5.  結果をInteractionの応答として送信。
*   **ヘルプ表示時 (`/remind help`)**:
    1.  Interactionを受け取る。
    2.  ボットの基本的な使い方、コマンド一覧、READMEへのリンクを含むEmbedを作成。
    3.  作成したEmbedをInteractionの応答（ephemeral）として送信。

## 7. 非機能要件（考慮事項）

*   **使いやすさ**: スラッシュコマンドによる直感的な操作。時刻指定の柔軟性。
*   **信頼性**: `apscheduler` による確実な時刻実行。DBによるリマインド情報の永続化。`misfire_grace_time` の設定。
*   **エラーハンドリング**: 不正な入力（時刻形式、ターゲット指定）や実行時エラー（DBエラー、APIエラー）に対する適切なフィードバック（ephemeralメッセージ）。
*   **タイムゾーン**: JST (`Asia/Tokyo`) 固定。

## 8. 今後の拡張可能性

*   設定済みリマインドの編集機能
*   繰り返しリマインドの再スケジュール処理の実装
*   より自然言語に近い時刻パース (`next tuesday at 3pm` など)
*   タイムゾーンのユーザー別設定
*   Web UIによる管理機能
*   一覧表示のページネーション
