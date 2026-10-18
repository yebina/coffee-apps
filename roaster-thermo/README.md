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
| 積層セラミックコンデンサー 0.01µF（秋月 108138） | 熱電対入力のノイズ対策（推奨） |
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

- Pmod TC1 の端子台の横にある **`RED` の印は − 側**。米国の色規格では K 型の赤線が − のため
- ミスミのプローブ（MSNDFL）は日本の色規格（JIS）で **赤 = ＋、白 = −**。つまり **白を `RED` の印の側、赤を反対側**に挿す。色の名前に引きずられて逆にしやすいので注意（2026-10-18 に実機で確認。赤を `RED` 側に挿すと、温めたときに表示が下がる）
- **0.01µF のコンデンサを、2つの端子に熱電対の線と一緒に挟む**（推奨）。2m のリード線が拾うノイズで、MAX31855 が SCG（GND 短絡）を一瞬だけ誤検出することがある。実測では、何も触らない状態での誤検出が 30 秒あたり約 20 回から約 2 回に減った。誤検出が 0.5 秒未満で収まればファーム側で無視するので、READ の値には影響しない
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

Artisan 4.2.0（macOS、`brew install --cask artisan`）で確認した手順。メニュー名は英語表示のもの（Config → Language → English で切り替え、再起動）。

1. **Config → Mode → Expert** にする。Default モードでは Device と Port のメニューが表示されない
2. **Config → Device...** の **ET/BT** タブで
   - 左の列の **TC4** のラジオボタンを選ぶ（Meter の一覧ではない）
   - Arduino TC4 の欄: ET Channel = **1**、BT Channel = **2**、AT Channel = **None**（初期値のまま）
   - **PID Firmware のチェックを外す**（このファームに PID 制御はない）
3. **Config → Port...** の ET/BT タブで
   - Comm Port: `CP2102N USB to UART Bridge Controller`（= `/dev/cu.usbserial-…`）
   - Baud Rate: **115200**（Byte Size 8 / Parity N / Stopbits 1 は初期値のまま）
4. **ON** を押すと左上に「TC4 initialized」と出て、BT が表示される。ET は 2 枚目の変換器を付けるまで `u.u`（値なし）
5. 華氏で表示されたら **Config → Temperature → Celsius Mode**。Artisan が `UNITS;` で単位を送ってくるので、ファーム側の設定は不要

最初の接続で「Arduino could not set channels」というエラーが 1 回だけ出ることがあるが、次のサンプリングで自動的に再接続されるので無視してよい。エラーが出続ける場合は Port 設定（ポート名、115200）を見直す。

`ls /dev/cu.*` で `usbserial` 系のデバイスが見えないときは、ケーブルが充電専用でないか確認する。それでも見えなければ Silicon Labs の CP210x ドライバを入れる。

## チャンネル割り当て

| 物理チャンネル | 割り当て | 状態 |
|---|---|---|
| 1 | ET | 未実装（2 枚目の変換器を追加予定） |
| 2 | BT（Pmod TC1、CS = GPIO5） | 実装済み |

Artisan の初期設定（`CHAN;1200` = ET が物理1、BT が物理2）に合わせてある。
