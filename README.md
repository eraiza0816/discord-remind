# Discord Remind Bot

Discord Remind Bot は、Discordサーバーでリマインダーを設定できるボットです。
指定した時間に、指定した相手（自分自身またはチャンネル）にメッセージを送信します。

## 使い方

リマインダーの操作は、スラッシュコマンド (`/remind`) を使って行います。

### リマインダーを設定する

`/remind set` コマンドで新しいリマインダーを設定します。

**コマンド:**
`/remind set target:<リマインド先> time:<リマインド時刻> message:<メッセージ内容>`

**パラメータ:**

*   `target`: リマインドを送る相手を指定します。
    *   `@me`: 自分自身にリマインドします。
    *   `#チャンネル名`: 指定したチャンネルにリマインドします (例: `#general`)。
    *   ユーザーメンション: 特定のユーザーにリマインドします (例: `@ユーザー名`)。
    *   チャンネルメンション: 特定のチャンネルにリマインドします (例: `<#チャンネルID>`)。
*   `time`: リマインドを実行する時刻を指定します。様々な形式で指定可能です。
    *   絶対時刻:
        *   `HH:MM` (例: `15:30`) - 今日の指定時刻。過去の場合は明日の時刻。
        *   `YYYY/MM/DD HH:MM` (例: `2024/12/31 23:59`)
    *   相対時刻 (`in` を使用):
        *   `in X minutes` (または `min`, `m`) (例: `in 30 minutes`, `in 5m`)
        *   `in X hours` (または `h`) (例: `in 2 hours`, `in 1h`)
        *   `in X days` (または `d`) (例: `in 3 days`)
        *   `in X seconds` (または `sec`, `s`) (例: `in 45 seconds`)
    *   その他:
        *   `tomorrow at HH:MM` (例: `tomorrow at 10:00`)
    *   繰り返し (毎週):
        *   `every day at HH:MM` (例: `every day at 9:00`)
        *   `every [曜日] at HH:MM` (例: `every monday at 10:30`, `every sat at 22:00`)
            *   曜日: `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`
*   `message`: リマインド時に送信するメッセージの内容です。

**実行例:**
`/remind set target:@me time:in 1 hour message:会議のリマインダー`
`/remind set target:#general time:tomorrow at 10:00 message:朝会を始めます`

### 設定したリマインダーの一覧を見る

`/remind list` コマンドで、自分が設定した有効なリマインダーの一覧を表示します。
リマインダーID、実行時刻、宛先、メッセージ内容、繰り返し設定などが表示されます。

**コマンド:**
`/remind list`

### リマインダーを削除する

`/remind delete` コマンドで、指定したIDのリマインダーを削除します。
リマインダーIDは、`/remind list` コマンドで確認できます。

**コマンド:**
`/remind delete reminder_id:<リマインダーID>`

**パラメータ:**

*   `reminder_id`: 削除したいリマインダーのID (数値)。

**実行例:**
`/remind delete reminder_id:123`

### ヘルプを表示する

`/remind help` コマンドで、ボットの基本的な使い方やコマンドの一覧、詳細なドキュメントへのリンクを表示します。

**コマンド:**
`/remind help`

## 注意事項

*   時刻の解釈はボットが動作しているサーバーのタイムゾーン (Asia/Tokyo) に基づきます。
*   繰り返し設定されたリマインダーは、指定されたルールに従って繰り返し通知されます。

ご不明な点があれば、サーバー管理者にお問い合わせください。
