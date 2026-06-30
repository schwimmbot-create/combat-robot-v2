#include "rgbLED.h"
#include "esp_err.h"
#include "esp_log.h"
#include <Adafruit_NeoPixel.h>

#if CONFIG_PM_ENABLE
  #include "esp_pm.h"
#endif

#include "sdkconfig.h"


static const char* TAG = "rgbLED";

rgbLED::rgbLED(uint16_t numPixels, uint8_t pin, neoPixelType pixelType)
: strip(numPixels, pin, pixelType),
  count(numPixels),
  pinNum(pin)
{}

void rgbLED::begin() {
#if CONFIG_PM_ENABLE
  // Create PM locks and acquire them. If for some reason the target doesn’t support it,
  // don’t crash — just skip locks.
  esp_err_t err = esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "np_no_ls", &_no_ls);
  if (err != ESP_ERR_NOT_SUPPORTED) ESP_ERROR_CHECK(err);

  err = esp_pm_lock_create(ESP_PM_CPU_FREQ_MAX, 0, "np_max_f", &_max_f);
  if (err != ESP_ERR_NOT_SUPPORTED) ESP_ERROR_CHECK(err);

  if (_no_ls)  ESP_ERROR_CHECK(esp_pm_lock_acquire(_no_ls));
  if (_max_f)  ESP_ERROR_CHECK(esp_pm_lock_acquire(_max_f));
#endif


  ESP_LOGI(TAG, "rgbLED Initializing...");

  strip.begin();
  strip.clear();
  strip.setBrightness(brightness);   // ensure 'brightness' has a sensible default
  strip.show();
  startTask();

}

void rgbLED::setBrightness(uint8_t b) {
  brightness = b;
  strip.setBrightness(brightness);
  if (curMode == STATIC) {
    strip.fill(strip.Color(lastR, lastG, lastB, lastW));
    strip.show();
  }
}

void rgbLED::setColor(uint8_t r, uint8_t g, uint8_t b, uint8_t w) {
  curMode = STATIC;
  lastR = r; lastG = g; lastB = b; lastW = w;
  colorChanged = true; // Signal the task to update
  ESP_LOGD(TAG,"Static Color Set");
}

 // Update setRainbow:
void rgbLED::setRainbow(bool enable, uint16_t speed_ms, uint8_t hue_step) {
  if (enable) {
    speedMs = speed_ms;
    hueStep = hue_step;
    curMode = RAINBOW;
    colorChanged = true; // Signal the task to update
    if (!task) startTask();
    ESP_LOGD(TAG,"Rainbow Color Enabled");
  } else {
    curMode = STATIC;
    colorChanged = true; // Signal the task to update
    ESP_LOGD(TAG,"Rainbow Color Disabled");
  }
}

void rgbLED::startTask() {
  if (task) return;
  xTaskCreate(taskFn, "rgbLEDTask", 3072, this, 2, &task);
}

void rgbLED::stopTask() {
  if (!task) return;
  vTaskDelete(task);
  task = nullptr;
}


void rgbLED::taskFn(void* arg) {
auto* self = static_cast<rgbLED*>(arg);

  for (;;) {
    if (self->curMode == RAINBOW) {
      // Draw a simple moving rainbow gradient; gamma-corrected
      for (uint16_t i = 0; i < self->count; ++i) {
        // Hue per pixel: base + i*hueStep (scaled to 0..65535)
        uint16_t hue = self->baseHue + (uint16_t)i * (uint16_t)self->hueStep * 256u;
        uint32_t c   = self->strip.ColorHSV(hue, 255, 255);   // HSV->RGB
        c            = self->strip.gamma32(c);                // gamma fix
        self->strip.setPixelColor(i, c);                      // (W channel remains 0)
      }
      self->strip.setBrightness(self->brightness);
      self->strip.show();

      self->baseHue += 256; // advance ~1/256 of full wheel per frame
      vTaskDelay(pdMS_TO_TICKS(self->speedMs));
    } else if (self->curMode == STATIC) {
      if (self->colorChanged) {
        self->strip.setBrightness(self->brightness);
        self->strip.fill(self->strip.Color(self->lastR, self->lastG, self->lastB, self->lastW));
        self->strip.show();
        self->colorChanged = false;
      }
      vTaskDelay(pdMS_TO_TICKS(100));
    } else {
      vTaskDelay(pdMS_TO_TICKS(100));
    }
  }
}
  
