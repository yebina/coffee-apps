// 焙煎温度ロガー: Pmod TC1 (MAX31855) -> ESP32 -> USB シリアル -> Artisan
//
// Artisan の「TC4」デバイスとして動く。Artisan 側の処理（src/artisanlib/comm.py の
// ARDUINOTC4temperature）に合わせて、次のコマンドに応答する。
//   CHAN;wxyz  ... 論理スロット1〜4に割り当てる物理チャンネル番号（0 = 未使用）。"#" で始まる行で応答
//   UNITS;C|F  ... 温度単位。"#" で始まる行で応答
//   FILT;...   ... フィルタ設定。受け付けるだけで使わない（平滑化はファーム側で固定）
//   READ       ... "周囲温度,スロット1,スロット2[,スロット3,スロット4]" を返す
// Artisan の初期設定は ET=チャンネル1、BT=チャンネル2（CHAN;1200）なので、
// Pmod TC1 を物理チャンネル2（BT）に割り当てておけば Artisan の設定変更なしで BT が出る。
// 物理チャンネル1（ET）は 2 枚目の変換器を足すまで -1（値なし）を返す。
//
// 動作確認用に DIAG（生データと故障ビットの表示）も受け付ける。

#include <Arduino.h>
#include <SPI.h>

// ---- 配線（ESP32-DevKitC-32E の VSPI）---------------------------------------
// Pmod TC1: 1=CS, 2=NC, 3=MISO, 4=SCK, 5=GND, 6=VCC(3.3V)
constexpr int PIN_SCK = 18;
constexpr int PIN_MISO = 19;
constexpr int PIN_MOSI = 23;  // MAX31855 は読み出し専用なので未接続でよい
constexpr int PIN_CS_BT = 5;  // Pmod TC1（BT）

constexpr long SERIAL_BAUD = 115200;
constexpr uint32_t SAMPLE_INTERVAL_MS = 100;  // MAX31855 の変換時間（最大100ms）に合わせる
constexpr int AVG_SAMPLES = 5;                // READ では直近 0.5 秒の平均を返す

// ---- MAX31855 ---------------------------------------------------------------
struct Max31855Reading {
  uint32_t raw;
  bool fault;
  bool openCircuit;   // OC: 熱電対が外れている／断線
  bool shortToGnd;    // SCG: 熱電対が GND と導通（接地型プローブが筐体に触れている等）
  bool shortToVcc;    // SCV: 熱電対が VCC と導通
  float thermocouple; // 熱電対温度 [℃]（0.25℃刻み）
  float internal;     // 冷接点（チップ）温度 [℃]（0.0625℃刻み）
};

const SPISettings MAX31855_SPI(4000000, MSBFIRST, SPI_MODE0);

Max31855Reading readMax31855(int csPin) {
  SPI.beginTransaction(MAX31855_SPI);
  digitalWrite(csPin, LOW);
  delayMicroseconds(1);
  uint32_t v = SPI.transfer32(0);
  digitalWrite(csPin, HIGH);
  SPI.endTransaction();

  Max31855Reading r{};
  r.raw = v;
  r.fault = v & (1UL << 16);
  r.shortToVcc = v & (1UL << 2);
  r.shortToGnd = v & (1UL << 1);
  r.openCircuit = v & (1UL << 0);

  // D31..D18: 14bit 符号付き、LSB = 0.25℃
  int16_t tc = static_cast<int16_t>((v >> 18) & 0x3FFF);
  if (tc & 0x2000) tc -= 0x4000;
  r.thermocouple = tc * 0.25f;

  // D15..D4: 12bit 符号付き、LSB = 0.0625℃
  int16_t in = static_cast<int16_t>((v >> 4) & 0x0FFF);
  if (in & 0x0800) in -= 0x1000;
  r.internal = in * 0.0625f;
  return r;
}

// ---- 移動平均 ---------------------------------------------------------------
class Averager {
 public:
  void add(float v) {
    buf_[next_] = v;
    next_ = (next_ + 1) % AVG_SAMPLES;
    if (count_ < AVG_SAMPLES) count_++;
  }
  void clear() { count_ = 0; next_ = 0; }
  bool empty() const { return count_ == 0; }
  float mean() const {
    float sum = 0;
    for (int i = 0; i < count_; i++) sum += buf_[i];
    return sum / count_;
  }

 private:
  float buf_[AVG_SAMPLES] = {};
  int next_ = 0;
  int count_ = 0;
};

// ---- 状態 -------------------------------------------------------------------
Averager btAvg;
Averager ambientAvg;
Max31855Reading lastBt{};
uint32_t lastSampleMs = 0;

char channelMap[4] = {'1', '2', '0', '0'};  // Artisan の初期値 CHAN;1200 と同じ
bool fahrenheit = false;

String rxLine;

void sample() {
  lastBt = readMax31855(PIN_CS_BT);
  ambientAvg.add(lastBt.internal);
  if (lastBt.fault) {
    // 故障中の値は捨て、READ では -1 を返す
    btAvg.clear();
  } else {
    btAvg.add(lastBt.thermocouple);
  }
}

float toUnits(float c) { return fahrenheit ? c * 9.0f / 5.0f + 32.0f : c; }

// 物理チャンネルの値。値がないときは NAN
float physicalChannel(char ch) {
  switch (ch) {
    case '2':
      return btAvg.empty() ? NAN : btAvg.mean();
    default:
      return NAN;  // '1'（ET）は未実装、'0' は未使用
  }
}

void printValue(float c) {
  if (isnan(c)) {
    Serial.print("-1");
  } else {
    Serial.print(toUnits(c), 2);
  }
}

void handleRead() {
  // 出力するスロット数: 最後の非ゼロのスロットまで（最低2 = ET, BT）
  int slots = 2;
  for (int i = 3; i >= 2; i--) {
    if (channelMap[i] != '0') {
      slots = i + 1;
      break;
    }
  }
  printValue(ambientAvg.empty() ? NAN : ambientAvg.mean());
  for (int i = 0; i < slots; i++) {
    Serial.print(',');
    printValue(physicalChannel(channelMap[i]));
  }
  Serial.println();  // Artisan は末尾 "\r\n" を前提に2文字削る
}

void handleDiag() {
  const Max31855Reading &r = lastBt;
  Serial.printf("# BT raw=0x%08lX tc=%.2fC internal=%.4fC fault=%d OC=%d SCG=%d SCV=%d\r\n",
                static_cast<unsigned long>(r.raw), r.thermocouple, r.internal, r.fault,
                r.openCircuit, r.shortToGnd, r.shortToVcc);
  if (r.raw == 0x00000000 || r.raw == 0xFFFFFFFF) {
    Serial.println("# 応答がありません。配線（CS/MISO/SCK/3V3/GND）を確認してください");
  } else if (r.openCircuit) {
    Serial.println("# 熱電対が接続されていないか、断線しています");
  } else if (r.shortToGnd || r.shortToVcc) {
    Serial.println("# 熱電対が GND/VCC と導通しています（接地型プローブや筐体との接触を確認）");
  }
}

void handleCommand(String cmd) {
  cmd.trim();
  if (cmd.isEmpty()) return;
  String upper = cmd;
  upper.toUpperCase();

  if (upper == "READ") {
    handleRead();
  } else if (upper.startsWith("CHAN;")) {
    String digits = cmd.substring(5);
    for (int i = 0; i < 4; i++) {
      char c = i < static_cast<int>(digits.length()) ? digits[i] : '0';
      channelMap[i] = (c >= '0' && c <= '4') ? c : '0';
    }
    Serial.printf("# Active channels set to %c%c%c%c\r\n", channelMap[0], channelMap[1],
                  channelMap[2], channelMap[3]);
  } else if (upper.startsWith("UNITS;")) {
    fahrenheit = upper.endsWith("F");
    Serial.println(fahrenheit ? "# Changed units to F" : "# Changed units to C");
  } else if (upper.startsWith("FILT;")) {
    Serial.println("# Filter settings ignored");
  } else if (upper == "DIAG") {
    handleDiag();
  }
  // それ以外のコマンドは黙って無視する（Artisan の READ 応答を乱さないため）
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(PIN_CS_BT, OUTPUT);
  digitalWrite(PIN_CS_BT, HIGH);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_CS_BT);
  delay(200);  // MAX31855 の初回変換を待つ
  sample();
}

void loop() {
  uint32_t now = millis();
  if (now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs = now;
    sample();
  }

  while (Serial.available()) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      handleCommand(rxLine);
      rxLine = "";
    } else if (rxLine.length() < 64) {
      rxLine += c;
    }
  }
}
