#!/usr/bin/env python3
"""Hardware timing bench for Motor, Servo, and ESC motion profiles.

Requires the robot AP, the real Robot Controller v2, and the USB mock 8BitDo dongle.
The script patches output configuration, drives inputs through the mock dongle, samples
/api/status, validates measured rise/fall times, and restores the original config.
"""
from __future__ import annotations
import argparse, json, time, urllib.request
from pathlib import Path
import serial

PROFILES = {
    "instant": (0, 0),
    "sport": (150, 100),
    "medium": (500, 350),
    "slow": (1200, 800),
    "custom": (700, 650),
}


def api(base, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type":"application/json"}, method="GET" if data is None else "POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def mock_cmd(port, command):
    port.reset_input_buffer(); port.write((command + "\n").encode()); port.flush()
    deadline=time.monotonic()+2; out=b""
    while time.monotonic()<deadline:
        out += port.read(port.in_waiting or 1)
        if b"MOCK OK" in out or out.startswith(b"OK "): return
    raise RuntimeError(f"mock command failed: {command}: {out.decode(errors='replace')}")


def wait_value(base, getter, predicate, timeout):
    start=time.monotonic(); samples=[]
    while time.monotonic()-start < timeout:
        s=api(base,"/api/status"); v=getter(s); samples.append((time.monotonic()-start,v))
        if predicate(v): return time.monotonic()-start, samples
        time.sleep(.025)
    raise RuntimeError(f"threshold timeout; last={samples[-1] if samples else None}")


def check_timing(label, configured, measured):
    if configured == 0:
        if measured > .22: raise RuntimeError(f"{label}: instant took {measured*1000:.0f} ms")
    else:
        expected=.90*configured/1000
        if not max(.04, expected*.50) <= measured <= expected*1.65 + .12:
            raise RuntimeError(f"{label}: measured {measured*1000:.0f} ms outside tolerance for {configured} ms")


def set_profile(base, output, accel, decel, extra):
    patch={output:{"acceleration_ms":accel,"deceleration_ms":decel,**extra}}
    result=api(base,"/api/config",patch)
    if not result.get("ok",False): raise RuntimeError(f"config rejected: {result}")
    time.sleep(.12)


def flatten_output(cfg):
    keys=("display_name","direction","servo_mode","deadzone","primary","secondary","motor_mode","purpose","protocol","semantics","active_high","default_state","digital_mode","digital_preset","digital_on_threshold","digital_off_threshold","digital_custom_pct","acceleration_ms","deceleration_ms")
    out={k:cfg[k] for k in keys if k in cfg}
    for nested,mapping in {
        "pulse":{"min_us":"min_pulse_us","center_us":"center_pulse_us","max_us":"max_pulse_us","frame_hz":"frame_hz","neutral_deadzone":"neutral_deadzone"},
        "safety":{"weapon":"weapon_safety","failsafe":"failsafe","weapon_mode":"weapon_mode","arming_source":"arming_source","deadman_source":"deadman_source"},
        "esc_arm":{"mode":"esc_arm_mode","source":"esc_arm_source","hold_ms":"esc_arm_hold_ms","low_us":"esc_arm_low_us","high_us":"esc_arm_high_us","low_ms":"esc_arm_low_ms","high_ms":"esc_arm_high_ms","final_low_ms":"esc_arm_final_low_ms"},
        "power":{"GOOD":"power_good","WARN":"power_warn","LOW":"power_low"},
        "pwm":{"frequency_hz":"pwm_frequency_hz","duty_pct":"pwm_duty_pct"},
    }.items():
        for source,target in mapping.items():
            if source in cfg.get(nested,{}): out[target]=cfg[nested][source]
    return out


def run(args):
    base=args.api_base.rstrip("/")
    original=api(base,"/api/config")
    ser=serial.Serial(args.mock_port,115200,timeout=.05)
    results=[]
    try:
        mock_cmd(ser,"RATE 30"); mock_cmd(ser,"RESET")
        # Motor M1: tank LY source; speed telemetry is 0..255.
        api(base,"/api/config",{"drive":{"layout":"differential","method":"tank","left_axis":"LY","right_axis":"RY"}})
        for name,(accel,decel) in PROFILES.items():
            set_profile(base,"M1",accel,decel,{"purpose":"drive","primary":"LY"})
            mock_cmd(ser,"SET LY=127 RY=127"); time.sleep(max(.3,decel/1000+0.25))
            mock_cmd(ser,"SET LY=0")
            rise,_=wait_value(base,lambda s:s["runtime"]["outputs"]["M1"]["speed"],lambda v:v>=225,max(1.0,accel/1000*2+0.5))
            mock_cmd(ser,"SET LY=127")
            fall,_=wait_value(base,lambda s:s["runtime"]["outputs"]["M1"]["speed"],lambda v:v<=25,max(1.0,decel/1000*2+0.5))
            check_timing(f"motor/{name}/accel",accel,rise); check_timing(f"motor/{name}/decel",decel,fall)
            results.append(("motor",name,rise,fall))
        # Servo S1: center to max and back, pulse telemetry 1500..2000 us.
        for name,(accel,decel) in PROFILES.items():
            set_profile(base,"S1",accel,decel,{"purpose":"servo","protocol":"rc_servo_pwm","semantics":"position_servo","primary":"LX","direction":"normal","servo_mode":"bi","min_pulse_us":1000,"center_pulse_us":1500,"max_pulse_us":2000,"frame_hz":50})
            mock_cmd(ser,"SET LX=127"); time.sleep(max(.3,decel/1000+0.25))
            mock_cmd(ser,"SET LX=255")
            rise,_=wait_value(base,lambda s:s["runtime"]["outputs"]["S1"]["pulse_us"],lambda v:v>=1945,max(1.0,accel/1000*2+0.5))
            mock_cmd(ser,"SET LX=127")
            fall,_=wait_value(base,lambda s:s["runtime"]["outputs"]["S1"]["pulse_us"],lambda v:v<=1555,max(1.0,decel/1000*2+0.5))
            check_timing(f"servo/{name}/accel",accel,rise); check_timing(f"servo/{name}/decel",decel,fall)
            results.append(("servo",name,rise,fall))
        # ESC S2: manual arming, forward-only RT, 1000..2000 us.
        for name,(accel,decel) in PROFILES.items():
            set_profile(base,"S2",accel,decel,{"purpose":"esc","protocol":"rc_esc_pwm","semantics":"esc_forward_only","primary":"RT","secondary":"NONE","esc_arm_mode":"manual","weapon_safety":False,"min_pulse_us":1000,"center_pulse_us":1500,"max_pulse_us":2000,"frame_hz":50})
            mock_cmd(ser,"SET R2=0"); time.sleep(max(.3,decel/1000+0.25))
            mock_cmd(ser,"SET R2=255")
            rise,_=wait_value(base,lambda s:s["runtime"]["outputs"]["S2"]["pulse_us"],lambda v:v>=1945,max(1.0,accel/1000*2+0.5))
            mock_cmd(ser,"SET R2=0")
            fall,_=wait_value(base,lambda s:s["runtime"]["outputs"]["S2"]["pulse_us"],lambda v:v<=1055,max(1.0,decel/1000*2+0.5))
            check_timing(f"esc/{name}/accel",accel,rise); check_timing(f"esc/{name}/decel",decel,fall)
            results.append(("esc",name,rise,fall))
        print("OUTPUT  PROFILE   ACCEL_MS  DECEL_MS")
        for output,name,rise,fall in results:
            print(f"{output:6}  {name:7}  {rise*1000:8.0f}  {fall*1000:8.0f}")
        print("BENCH_MOTION_PROFILES PASS")
    finally:
        try: mock_cmd(ser,"RESET")
        except Exception as exc: print(f"WARN mock reset during cleanup: {exc}")
        finally: ser.close()
        restore={k:flatten_output(v) for k,v in original.get("outputs",{}).items()}
        restore["drive"]=original.get("drive",{})
        result=api(base,"/api/config",restore)
        if not result.get("ok",False): raise RuntimeError(f"configuration restore failed: {result}")


def main():
    p=argparse.ArgumentParser(); p.add_argument("--api-base",default="http://192.168.4.1"); p.add_argument("--mock-port",default="/dev/ttyACM0")
    run(p.parse_args())
if __name__ == "__main__": main()
