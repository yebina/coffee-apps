# roaster-thermo

手回し焙煎機（KALDI Mini）用の温度ロガー。K 型熱電対の温度を ESP32 で読み、USB シリアル経由で [Artisan](https://artisan-scope.org/) に送る。

```
K型熱電対 → Pmod TC1（MAX31855） → ESP32-DevKitC-32E → USB → Mac（Artisan）
```

Artisan からは **TC4 互換デバイス**として見えるので、Artisan 側は機種で「TC4」を選ぶだけでよい。

## 部品

| 部品 | 用途 |
|---|---|
| ESP32-DevKitC-32E（秋月 115673） | マイコン |
| Digilent Pmod TC1 | 熱電対の変換器（MAX31855、冷接点補償つき） |
| ジャンパー線 メス-メス（秋月 103475） | ESP32 と Pmod TC1 の配線（5本） |
| 積層セラミックコンデンサー 0.01µF（秋月 108138） | 熱電対入力のノイズ対策（任意） |
| ミスミ MSNDFL1.6-200-F2-N | BT 用シース K 熱電対（非接地型、φ1.6×200mm、リード線 2m、端子なし） |
| USB-C to micro-B ケーブル（データ通信対応） | Mac と ESP32 の接続 |

## 配線

Pmod TC1 のピン番号は、基板の「1」の印がある側から数える。

| Pmod TC1 | 信号 | ESP32-DevKitC-32E |
|---|---|---|
| 1 | CS | **GPIO5**（基板の印字 `5`） |
| 2 | NC | 接続しない |
| 3 | MISO | **GPIO19**（`19`） |
| 4 | SCK | **GPIO18**（`18`） |
| 5 | GND | **GND** |
| 6 | VCC | **3V3**（5V には繋がない） |

熱電対は Pmod TC1 の青い端子台に差し込む。

- Pmod TC1 の端子台の横にある **`T-` / `RED` の印は − 側**。米国の色規格では K 型の赤線が − のため
- ミスミのプローブは日本の色規格（JIS）で **赤 = ＋、白 = −**。つまり **白を `T-`（RED の印）側、赤を反対側**に挿す。色の名前に引きずられて逆にしやすいので注意
- 0.01µF のコンデンサを使う場合は、2つの端子に熱電対の線と一緒に挟む
- 逆に挿すと、温めたときに温度が下がる。そのときは入れ替える

## ビルドと書き込み

[PlatformIO](https://platformio.org/) を使う。

```bash
brew install platformio
```

```bash
cd roaster-thermo/firmware && pio run -t upload
```

書き込みが始まらない場合は、ESP32 の **BOOT ボタンを押したまま** もう一度実行する。

## 動作確認（Artisan を使う前に）

```bash
cd roaster-thermo/firmware && pio device monitor
```

モニタが開いたら、次のコマンドを打って Enter を押す（終了は `Ctrl+C`）。

| コマンド | 応答の例 | 意味 |
|---|---|---|
| `READ` | `24.50,-1,25.75` | 周囲温度（Pmod TC1 の基板温度）, ET（未接続なので -1）, BT |
| `DIAG` | `# BT raw=0x... tc=25.75C ...` | 生データと故障ビット |

`DIAG` の表示で切り分けられる症状:

| 表示 | 原因 |
|---|---|
| `応答がありません` | 配線ミス（CS / MISO / SCK / 3V3 / GND） |
| `OC=1` | 熱電対が刺さっていない、または断線 |
| `SCG=1` / `SCV=1` | 熱電対が GND / VCC と導通。接地型プローブや筐体との接触を疑う |

熱電対の先端を指でつまんで、`READ` の BT（3つ目の値）が上がれば成功。

## Artisan の設定

1. **Config → Device** で Meter に **TC4** を選ぶ
   - ET Channel = **1**、BT Channel = **2**（初期値のまま）
2. **Config → Port** で
   - Comm Port: `/dev/cu.usbserial-…` または `/dev/cu.SLAB_USBtoUART`
   - Baud Rate: **115200**
3. **ON** を押すと BT が表示される。ET は 2 枚目の変換器を付けるまで表示されない

Artisan がポートを開くと ESP32 が自動で再起動する（DevKitC の自動リセット回路のため）。そのため最初の 1 回だけ「Arduino could not set channels」というエラーが出ることがあるが、次のサンプリング（約 3 秒後）で自動的に再接続されるので無視してよい。エラーが出続ける場合は Port 設定（ポート名、115200）を見直す。

`ls /dev/cu.*` で `usbserial` 系のデバイスが見えないときは、ケーブルが充電専用でないか確認する。それでも見えなければ Silicon Labs の CP210x ドライバを入れる。

## チャンネル割り当て

| 物理チャンネル | 割り当て | 状態 |
|---|---|---|
| 1 | ET | 未実装（2 枚目の変換器を追加予定） |
| 2 | BT（Pmod TC1、CS = GPIO5） | 実装済み |

Artisan の初期設定（`CHAN;1200` = ET が物理1、BT が物理2）に合わせてある。
