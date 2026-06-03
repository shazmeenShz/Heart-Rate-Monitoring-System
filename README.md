# ❤️ Heart Rate Monitoring System using MAX30102, Arduino Nano & Python GUI

A real-time Heart Rate Monitoring System developed using the **MAX30102 Heart Rate Sensor**, **Arduino Nano**, **OLED Display**, and a **Python-based Desktop Dashboard**. The system continuously monitors heart rate, calculates BPM (Beats Per Minute), and displays the data simultaneously on an OLED screen and a laptop GUI.

---

# 📌 Project Overview

This project combines embedded systems and software development to create a compact healthcare monitoring solution.

The MAX30102 sensor captures pulse signals from the user's fingertip. The Arduino Nano processes the sensor data and calculates heart rate values, which are displayed on an OLED screen in real time.

To enhance visualization and user interaction, a Python-based desktop application was also developed. The GUI receives live data from the Arduino through serial communication and displays the readings on a laptop screen.

---

# ✨ Key Features

✅ Real-Time Heart Rate Monitoring

✅ BPM (Beats Per Minute) Calculation

✅ MAX30102 Sensor Integration

✅ OLED Display Output

✅ Python GUI Dashboard

✅ Live Serial Communication

✅ Simultaneous OLED and Laptop Monitoring

✅ Health Status Indication

✅ LED and Buzzer Alerts

✅ Compact and Portable Design

---

# 🛠 Hardware Components

* Arduino Nano
* MAX30102 Heart Rate Sensor
* 0.96" OLED Display (I2C)
* LEDs
* Buzzer
* Breadboard
* Jumper Wires
* USB Cable

---

# 💻 Software Components

* Arduino IDE
* Python
* Tkinter (GUI Development)
* PySerial (Serial Communication)
* Adafruit SSD1306 Library
* Adafruit GFX Library
* SparkFun MAX3010x Library

---

# ⚙️ Working Principle

### Sensor Data Acquisition

The MAX30102 sensor uses red and infrared LEDs along with a photodetector to measure variations in blood flow through the fingertip.

### Signal Processing

The Arduino Nano processes the acquired PPG (Photoplethysmography) signals and calculates the heart rate in BPM.

### OLED Display

The calculated values are displayed on a 0.96" OLED display in real time.

### Python Dashboard

The Arduino sends data to a laptop through serial communication.

The Python GUI receives this data and displays:

* Heart Rate (BPM)
* Health Status
* Live Monitoring Information

This enables monitoring on both the hardware display and the computer screen simultaneously.

---

# 🖥️ Desktop GUI Features

### Dashboard Capabilities

* Real-Time BPM Display
* Live Data Monitoring
* Health Status Display
* Serial Communication Interface
* User-Friendly Graphical Interface

### Technologies Used

* Python
* Tkinter
* PySerial

### Benefits

* Better Data Visualization
* Larger Display Area
* Easy Demonstration and Presentation
* Future Expansion for IoT Applications

---

# 📊 Parameters Monitored

### ❤️ Heart Rate (BPM)

The system continuously calculates and displays the user's heart rate in Beats Per Minute.

| Heart Rate Status | BPM Range |
| ----------------- | --------- |
| Low               | Below 60  |
| Normal            | 60 - 100  |
| High              | Above 100 |

### 🩺 Blood Pressure (Educational Estimation)

The project includes software-based blood pressure estimation for demonstration purposes. These values are not medically certified and should not be considered clinical measurements.

---

# 🔄 System Architecture

MAX30102 Sensor
⬇
Arduino Nano
⬇
OLED Display
⬇
USB Serial Communication
⬇
Python GUI Dashboard

---

# 📸 Project Gallery

## Hardware Setup

(Add Hardware Setup Image Here)

## OLED Display Output

(Add OLED Display Image Here)

## Python GUI Dashboard

(Add GUI Screenshot Here)

## Final Working Prototype

(Add Final Prototype Image Here)

---

# 🎯 Applications

* Health Monitoring Systems
* Biomedical Engineering Projects
* Embedded Systems Learning
* IoT Healthcare Applications
* Academic Demonstrations
* Research and Prototyping

---

# 📚 Skills Demonstrated

* Embedded Systems Development
* Arduino Programming
* Python Programming
* GUI Development
* Sensor Interfacing
* Serial Communication
* I2C Communication
* Real-Time Data Processing
* Hardware Debugging
* System Integration

---

# 🚀 Future Improvements

* Accurate SpO₂ Measurement
* Bluetooth Connectivity
* Mobile Application Integration
* Cloud Data Logging
* Wearable Device Development
* Health Data Analytics Dashboard

---

# ⚠️ Disclaimer

This project is intended for educational and research purposes only. It is not designed to replace certified medical equipment or provide clinical diagnoses.

---

# ⭐ Support

If you found this project interesting, consider giving this repository a ⭐ Star.

Thank you for visiting this project!
