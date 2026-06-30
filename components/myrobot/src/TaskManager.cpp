
#include <TaskManager.h>
#include <Arduino.h>
#include <Constants.h>
#include <Drum.h>
#include <Drive.h>
#include <PowerFunctions.h>
#include <Buttons.h>
#include "esp_log.h"
#include "LED.h"
#include "rgbLED.h"
#include <Adafruit_NeoPixel.h>
#include "esp_pm.h"


#include "esp_task_wdt.h"



static const char* TAG = "TaskManager";

TaskManager::TaskManager()
  : drum(ESC_1_PIN),
    buttons(MODE_BUTTON_PIN),
    led(DEBUG_LED_PIN),
    ledStrip(4, ESC_2_PIN, NEO_GRBW + NEO_KHZ800),
    _isConnected(false),
    _leftDriveInput(0),
    _rightDriveInput(0),
    _forwardEscInput(0),
    _reverseEscInput(0),
    lastUpdateTime(0),
    _controllerTimeout(CONTROLLER_TIMEOUT),
    motorsStopped(true),
    pendingUpdate(false),
    taskHandle(nullptr)
{}

void TaskManager::begin(){


    drive.begin();
    drive.setForwardInputLimits(511,-512);
    drive.setLateralInputLimits(-512,511);

    drum.begin();
    drum.setInputLimits(0,1023);

    powerFunctions.begin();

    buttons.begin();

    led.begin();

    //vTaskDelay(pdMS_TO_TICKS(100));

    esp_pm_lock_handle_t pm_lock;
    esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "no_light_sleep", &pm_lock);
    esp_pm_lock_acquire(pm_lock);


    ledStrip.begin();
    ledStrip.setBrightness(255);
    ledStrip.setColor(255, 0, 0, 0);


    // create the RTOS task (adjust stack if you overflow)
    xTaskCreatePinnedToCore(
        managerTask,           // function
        "TaskManager",         // name
        4096,                  // stack size in bytes
        this,                  // pvParameters
        tskIDLE_PRIORITY + 1,  // priority
        &taskHandle,           // handle
        APP_CPU_NUM            // core
    );
}

void TaskManager::managerTask(void* pvParameters) {
    auto* self = static_cast<TaskManager*>(pvParameters);
    TickType_t lastWake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(50);  // adjust as needed

    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));

    for (;;) {

        vTaskDelayUntil(&lastWake, period);

        self->batteryState = self->powerFunctions.getBatteryState();
        
        //If there's a new controller update pending, apply it
        if (self->pendingUpdate) {
            if (self->_isConnected) {
                if( self->batteryState != BATTERY_LOW || !ENABLE_LOW_BATTERY_SHUTDOWN){
                    //Put in things that can be ONLY be updated if the battery is not low
                    //This is the safer section as it protects the battery from overdrain
                    self->drive.two_stick_drive(self->_leftDriveInput, self->_rightDriveInput, self->currentOrientation);
                    self->drum.setSpeed(self->_forwardEscInput, self->_reverseEscInput);
                    self->motorsStopped = false;
                }
                //Put in things that can be updated even if voltage is low
                //Be careful not to put anything that could draw high current and could overdrain the battery
                //---------------------------------------------------------------
                self->adjustLedForBattery();


                //---------------------------------------------------------------

                
                self->lastUpdateTime = xTaskGetTickCount() * portTICK_PERIOD_MS;
            }
            else {
                self->stopAllMotors();
            }
            // clear the flag so we don't reapply next loop
            self->pendingUpdate = false;
        }

        //If we've timed out or lost connection, stop motors 
        if ((xTaskGetTickCount() * portTICK_PERIOD_MS - self->lastUpdateTime) >= self->_controllerTimeout ||
        self->_isConnected == false){
            self->stopAllMotors();
            self->ledStrip.setColor(0, 0, 255, 0);        // Blue LEDs indicate the controller has timed out
        } 


        ButtonPress buttonVal = self->buttons.checkForPress();
  
        switch(buttonVal){
            case BUTTON_NONE:
            break;

            case BUTTON_SHORT: {
            ESP_LOGI(TAG,"Button: Short Press");
            self->led.enqueuePattern("---", false, 255);
            }
                
            break;

            case BUTTON_LONG:
            ESP_LOGI(TAG,"Button: Long Press");
            self->led.enqueuePattern(".-.", false, 255);                  
            break;
            
            default:
            break;
        }

        ESP_ERROR_CHECK(esp_task_wdt_reset());   // feed for THIS task
    }
}


/**
 * Update the task manager with recent controller values
 * @param isConnected         Is the controller actively connected
 * @param ControllerState     Pass the values of the controller inputs
 *    
 */
void TaskManager::update(bool isConnected, const ControllerState& cs){
    _isConnected = isConnected;
    _leftDriveInput   = cs.leftStickY;
    _rightDriveInput  = cs.rightStickY;
    _forwardEscInput  = cs.rightTrigger;
    _reverseEscInput  = cs.leftTrigger;
    processButtons(cs);
    pendingUpdate     = true;
}

//Stop all motors in the robot. If everything is already stopped, it will pass
void TaskManager::stopAllMotors(){
    if(motorsStopped == false){
        ESP_LOGI(TAG, "Stopping Motors");
        drive.stop();
        drum.stop();
        motorsStopped = true;
    }
}

void TaskManager::processButtons(const ControllerState& cs){
    static bool prevA = 0, prevB = 0, prevX = 0, prevY = 0;

    bool A = (cs.buttons >> 0) & 0x01;
    bool B = (cs.buttons >> 1) & 0x01;
    bool X = (cs.buttons >> 2) & 0x01;
    bool Y = (cs.buttons >> 3) & 0x01;

    if( prevY == 0 && Y == 1){
        flipOrientation();
    }

    prevA = A;
    prevB = B;
    prevX = X;
    prevY = Y;
}


void TaskManager::flipOrientation(){
    if( currentOrientation == RIGHTSIDE_UP ){
        currentOrientation = UPSIDE_DOWN;
    }
    else{
        currentOrientation = RIGHTSIDE_UP;
    }
    ESP_LOGI(TAG,"Orientation Flipped.");
}

void TaskManager::adjustLedForBattery(){
    //Battery‐State check and update LED to indicate the level
    static int lastBatteryState = -1;
    
    if(lastBatteryState != batteryState || true){ //Only update if there is a change in the battery state from last time
        switch (batteryState) {
            case BATTERY_GOOD:
                ledStrip.setRainbow(true, 20, 25);   // effect for "good"
                break;

            case BATTERY_WARN:
                ledStrip.setColor(255, 255, 0, 0);      // yellow
                break;

            case BATTERY_LOW:
                ledStrip.setColor(255, 0, 0, 0);        // red
                if (ENABLE_LOW_BATTERY_SHUTDOWN) {
                    stopAllMotors();                 // one-shot on transition to LOW
                }
                break;
            default:
                ledStrip.setColor(255, 0, 0, 0);        // red
                break;
        }
    }

    lastBatteryState = batteryState;
}