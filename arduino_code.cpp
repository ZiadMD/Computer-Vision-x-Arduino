// Listen for a numeric count (0-5) over Serial and light LEDs accordingly.
// Mapping assumption: LEDs on pins 2..6 correspond to positions 1..5. When count=N,
// the first N LEDs (pins 2..(1+N)) are set HIGH and the rest LOW. When count=0, all off.

const int LED_PINS[] = {2, 3, 4, 5, 6};
const int NUM_LEDS = sizeof(LED_PINS) / sizeof(LED_PINS[0]);

void setup() {
  for (int i = 0; i < NUM_LEDS; ++i) {
    pinMode(LED_PINS[i], OUTPUT);
    digitalWrite(LED_PINS[i], LOW);
  }

  Serial.begin(9600);
  // For native-USB boards wait for serial to be ready
  #if defined(USBCON) || defined(ARDUINO_ARCH_SAM) || defined(ARDUINO_ARCH_SAMD)
    while (!Serial) {
      ;
    }
  #endif

  Serial.println("ARDUINO READY");
}

void setLedsCount(int n) {
  if (n < 0) n = 0;
  if (n > NUM_LEDS) n = NUM_LEDS;
  for (int i = 0; i < NUM_LEDS; ++i) {
    if (i < n) digitalWrite(LED_PINS[i], HIGH);
    else digitalWrite(LED_PINS[i], LOW);
  }
}

String trimString(String s) {
  // trim leading/trailing whitespace including CR/LF
  int start = 0;
  while (start < s.length() && isWhitespace(s.charAt(start))) start++;
  int end = s.length() - 1;
  while (end >= start && isWhitespace(s.charAt(end))) end--;
  if (end < start) return String("");
  return s.substring(start, end + 1);
}

bool isWhitespace(char c) {
  return (c == ' ' || c == '\t' || c == '\r' || c == '\n');
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line = trimString(line);
    if (line.length() == 0) return;

    // Try to parse as integer
    bool parsed = true;
    int val = 0;
    // allow optional leading plus/minus
    int idx = 0;
    if (line.charAt(0) == '+' || line.charAt(0) == '-') idx = 1;
    for (int i = idx; i < line.length(); ++i) {
      char c = line.charAt(i);
      if (c < '0' || c > '9') {
        parsed = false;
        break;
      }
    }

    if (parsed) {
      val = line.toInt();
      // clamp to valid range
      if (val < 0) val = 0;
      if (val > NUM_LEDS) val = NUM_LEDS;
      setLedsCount(val);
      Serial.print("ACK: ");
      Serial.println(val);
    } else {
      // Unknown command: respond with error
      Serial.print("ERR: unknown command: ");
      Serial.println(line);
    }
  }
}
