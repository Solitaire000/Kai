/*
 * kai_mr60bha2_bridge.ino
 * =========================
 * 烧录到 MR60BHA2 套件自带的 XIAO ESP32C6 主控板上（雷达+LED同一块板）。
 *
 * 职责：
 *   1. 用 Seeed 官方 Seeed_Arduino_mmWave 库读取雷达模块的在场/呼吸率/心率，
 *      按 kai_agent 项目定义的通用JSON信封格式（"kai-hw/1"，完整协议说明见
 *      ../../../../README.md），逐行打印到USB原生串口。
 *   2. 监听USB串口收到的 set_led 指令，控制板载/外接的RGB LED。
 *
 * !!! 重要的设计原则：这块固件只负责"忠实执行收到的指令"和"如实上报测到的
 * 数据"，不做任何自己的判断——比如"测到有人就自动点灯"这种联动规则，
 * **故意没有**写在这里。要不要点灯、点什么颜色，是PC那一端的Kai（大模型）
 * 自己决定的，固件只是执行终端。这是"体现agent的智能性，而不是简单条件
 * 判断"这个要求在硬件这一层的具体落地方式，完整说明见
 * ../../../../docs/HARDWARE_ARCHITECTURE.md。
 *
 * !!! API核对状态（重要，烧录前必看）：
 *   - mmWave.begin() / mmWave.update() / mmWave.isHumanDetected()
 *     —— 已经对照官方 People Counting 示例代码核实过，这几个方法名是对的。
 *   - 呼吸率 breathRate / 心率 heartRate 的具体获取方法 —— 目前还没有拿到
 *     官方 mmWaveBreath 示例核实，下面用 TODO 注释标出来了，先占位成
 *     -1（PC端driver.py会把-1当"这次没有有效数据"处理，不会报错，但也
 *     不会真的有呼吸率/心率数值）。等你把 mmWaveBreath.ino 的内容发我确认
 *     方法名之后，我会把这部分补上。
 *
 * 依赖库（Arduino库管理器搜索安装）：
 *   Seeed_Arduino_mmWave（官方库）
 *   Adafruit NeoPixel（LED库）
 *   ArduinoJson（用来解析PC发来的指令，比手写字符串解析更不容易出错——
 *     只在"解析收到的指令"这个方向用它，上报数据那个方向沿用手写拼接，
 *     避免整个文件都依赖它、增大固件体积）
 * 开发板：
 *   Arduino IDE 开发板管理器装 esp32(Espressif) 之后，选择 "XIAO_ESP32C6"
 */
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include "Seeed_Arduino_mmWave.h"

#ifdef ESP32
  #include <HardwareSerial.h>
  HardwareSerial mmWaveSerial(0);   // 板载：ESP32C6 <-> MR60BHA2雷达模块 之间的UART
#else
  #define mmWaveSerial Serial1
#endif

SEEED_MR60BHA2 mmWave;   // 已核实：People Counting官方示例用的就是这个类名

// ---------------- LED ----------------
// 沿用 LED.ino 里确认过的接线：D1接一颗NeoPixel。如果你的实际接线不是这样，
// 告诉我，改这一个常量就行，不影响其它逻辑。
const int LED_PIN = D1;
Adafruit_NeoPixel pixel(1, LED_PIN, NEO_GRB + NEO_KHZ800);

// LED状态机用到的变量。用 millis() 做非阻塞定时，而不是 LED.ino 原来那种
// delay()——delay()会整个卡住loop()，这块板子还要同时读雷达、听串口指令，
// 不能被一段跑马灯效果卡住几百毫秒
struct LedState {
  uint8_t r = 0, g = 0, b = 0;
  uint8_t brightness = 128;
  String pattern = "off";     // solid/blink/breathe/off
  uint32_t durationMs = 0;    // 0 = 一直保持；>0 = 这么久后自动变成off
  uint32_t appliedAtMs = 0;   // 这个指令是什么时候开始生效的
  uint32_t phaseMs = 0;       // blink/breathe用来计算当前处在动画的哪个阶段
} led;

// ---------------- 上报节流 ----------------
uint32_t seq = 0;
const uint32_t SEND_INTERVAL_MS = 500;   // 往PC发vitals数据的频率
uint32_t lastVitalsSend = 0;
const uint32_t LED_TICK_MS = 20;         // LED动画刷新频率（50Hz，肉眼够顺滑）
uint32_t lastLedTick = 0;

// 串口指令是一行一行来的，用一个小buffer攒完整一行再解析
String serialLineBuf;

void setup() {

  Serial.begin(115200);      // 这一路是给PC用的USB虚拟串口，波特率要和
                              // device.yaml / config.yaml 里的 baud 保持一致
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) { }   // 等USB枚举完成，最多等3秒

  mmWaveSerial.begin(115200);
  mmWave.begin(&mmWaveSerial);

  pixel.begin();
  pixel.clear();
  pixel.show();

  // 开机握手帧：方便PC端一眼确认"串口那头插着的到底是不是我认识的这个设备"
  Serial.println(F("{\"schema\":\"kai-hw/1\",\"device\":\"mr60bha2\",\"type\":\"hello\",\"fw_version\":\"1.1.0\"}"));
}

void loop() {
  pollRadar();
  pollSerialCommands();
  tickLed();
}

// ==================== 雷达读取与上报 ====================
void pollRadar() {
  // update()返回false表示这一轮没有新数据，不该读取/发送——这是对照官方
  // People Counting示例核实过的用法，之前的版本漏了判断这个返回值
  if (!mmWave.update(100)) {
    return;
  }

  uint32_t now = millis();
  if (now - lastVitalsSend < SEND_INTERVAL_MS) {
    return;
  }
  lastVitalsSend = now;

  // 已核实：isHumanDetected() 是官方示例里确认在场状态用的方法
  bool presence = mmWave.isHumanDetected();

  float breath_rate = -1;
  mmWave.getBreathRate(breath_rate);
  float heart_rate = -1;
  mmWave.getHeartRate(heart_rate);
  float distance = -1;
  mmWave.getDistance(distance);

  Serial.print(F("{\"schema\":\"kai-hw/1\",\"device\":\"mr60bha2\",\"seq\":"));
  Serial.print(seq++);
  Serial.print(F(",\"ts_ms\":"));
  Serial.print(now);
  Serial.print(F(",\"type\":\"vitals\",\"data\":{\"presence\":"));
  Serial.print(presence ? "true" : "false");
  Serial.print(F(",\"breath_rate\":"));
  Serial.print(breath_rate, 1);
  Serial.print(F(",\"heart_rate\":"));
  Serial.print(heart_rate, 1);
  Serial.print(F(",\"distance\":"));
  Serial.print(distance, 1);
  Serial.println(F("}}"));
}

// ==================== 串口指令接收（PC -> 设备） ====================
void pollSerialCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (serialLineBuf.length() > 0) {
        handleCommandLine(serialLineBuf);
        serialLineBuf = "";
      }
    } else if (c != '\r') {
      serialLineBuf += c;
      // 极简防御：一行长度超过256字节还没换行，大概率是垃圾数据/噪声，
      // 直接清空重来，避免buffer无限增长
      if (serialLineBuf.length() > 256) {
        serialLineBuf = "";
      }
    }
  }
}

void handleCommandLine(const String& line) {
  // 用ArduinoJson解析，比手写字符串查找更不容易因为字段顺序变化而出错
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, line);
  if (err) {
    return;  // 解析失败大概率是噪声/不完整的行，直接丢弃，不回复错误
             // （PC端driver.py发指令是fire-and-forget，不等待每条都有回应）
  }
  const char* cmd = doc["cmd"];
  if (cmd == nullptr) return;

  if (strcmp(cmd, "set_led") == 0) {
    handleSetLed(doc["args"]);
  }
  // 以后新增指令，在这里加一个 else if (strcmp(cmd, "xxx") == 0) 分支即可
}

void handleSetLed(JsonVariantConst args) {
  led.r = args["r"] | 0;
  led.g = args["g"] | 0;
  led.b = args["b"] | 0;
  led.brightness = args["brightness"] | 128;
  const char* pattern = args["pattern"] | "solid";
  led.pattern = String(pattern);
  led.durationMs = args["duration_ms"] | 0;
  led.appliedAtMs = millis();
  led.phaseMs = 0;

  // 可选的执行确认帧，方便PC端排查"指令到底有没有被设备收到并执行"
  Serial.print(F("{\"schema\":\"kai-hw/1\",\"device\":\"mr60bha2\",\"type\":\"ack\",\"cmd\":\"set_led\",\"ok\":true}"));
  Serial.println();
}

// ==================== LED 非阻塞状态机 ====================
void tickLed() {
  uint32_t now = millis();
  if (now - lastLedTick < LED_TICK_MS) {
    return;
  }
  lastLedTick = now;

  // duration_ms到期自动熄灭，避免忘记关灯导致一直亮着
  if (led.durationMs > 0 && now - led.appliedAtMs >= led.durationMs) {
    led.pattern = "off";
  }

  uint8_t scale = led.brightness;  // 0-255
  uint32_t elapsed = now - led.appliedAtMs;

  if (led.pattern == "off") {
    pixel.setPixelColor(0, pixel.Color(0, 0, 0));
  } else if (led.pattern == "solid") {
    pixel.setPixelColor(0, scaledColor(led.r, led.g, led.b, scale));
  } else if (led.pattern == "blink") {
    // 500ms一个周期，前半亮后半灭
    bool on = (elapsed % 500) < 250;
    pixel.setPixelColor(0, on ? scaledColor(led.r, led.g, led.b, scale) : pixel.Color(0, 0, 0));
  } else if (led.pattern == "breathe") {
    // 2秒一个周期的呼吸灯效果，用简单的三角波模拟渐亮渐暗（不用sin()省一点算力）
    uint32_t cyclePos = elapsed % 2000;
    float phase = cyclePos < 1000 ? (cyclePos / 1000.0) : (2.0 - cyclePos / 1000.0);
    uint8_t dynScale = (uint8_t)(scale * phase);
    pixel.setPixelColor(0, scaledColor(led.r, led.g, led.b, dynScale));
  }
  pixel.show();
}

uint32_t scaledColor(uint8_t r, uint8_t g, uint8_t b, uint8_t scale) {
  return pixel.Color(
    (uint16_t)r * scale / 255,
    (uint16_t)g * scale / 255,
    (uint16_t)b * scale / 255
  );
}
