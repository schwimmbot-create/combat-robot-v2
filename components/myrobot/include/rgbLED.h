#ifndef RGBLED_H
#define RGBLED_H

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include "esp_pm.h"


class rgbLED {
public:
  enum Mode : uint8_t { STATIC, RAINBOW };

  // pixelType defaults to RGBW @ 800kHz (SK6812). For RGB strips use NEO_GRB + NEO_KHZ800.
  rgbLED(uint16_t numPixels, uint8_t pin, neoPixelType pixelType = NEO_GRBW + NEO_KHZ800);

  // Initialize the strip (does not start any animation).
  void begin();

  // Brightness 0..255 (applies to both static color and rainbow)
  void setBrightness(uint8_t b);

  // Set a static color and show it immediately (disables rainbow)
  void setColor(uint8_t r, uint8_t g, uint8_t b, uint8_t w = 0);

  // Enable/disable rainbow chaser. When enabled, it runs in the background task.
  // speed_ms: delay between frames. hueStep: hue delta between adjacent pixels.
  void setRainbow(bool enable, uint16_t speed_ms = 30, uint8_t hueStep = 10);

  // Current mode / task status
  Mode mode() const { return curMode; }
  bool taskRunning() const { return task != nullptr; }

private:
  static void taskFn(void* arg);
  void startTask();
  void stopTask();

  Adafruit_NeoPixel strip;
  TaskHandle_t task = nullptr;

  const uint16_t count;
  const uint8_t  pinNum;

  // user controls (can change at runtime)
  volatile uint8_t  brightness = 128;
  volatile Mode     curMode    = STATIC;
  volatile uint16_t speedMs    = 30;
  volatile uint8_t  hueStep    = 10;

  
  volatile bool colorChanged = false; 

  // state
  volatile uint16_t baseHue    = 0;     // 0..65535 for ColorHSV
  uint8_t lastR = 0, lastG = 0, lastB = 0, lastW = 0; // for STATIC re-show

  #if CONFIG_PM_ENABLE
    esp_pm_lock_handle_t _no_ls = nullptr;
    esp_pm_lock_handle_t _max_f = nullptr;
  #endif
};
#endif  // RGBLED_H
