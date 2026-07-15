# SWS3025 (2026) — Artificial Intelligence of Things — Complete Course Reference

> **Purpose**: Consolidated reference for AIoT project development.  
> **Coverage**: Lectures 01–09 (full course) + Group Project Briefing.  
> **Last updated**: 2026-07-13

---

## Lecture 01 — Introduction to AIoT

### Core Concepts

| Concept | Definition |
|:---|:---|
| **IoT** | Physical devices connected via network, exchanging data; embed electronics, software, sensors, actuators, and connectivity |
| **IoT System** | Designed for specific applications; in-network data processing; interacts with external networks (e.g., Internet); distinct from mere device collections |
| **AIoT** | AI + IoT integration; enables intelligent operations in IoT systems; optimizes human-computer interaction, data management, and decision-making |
| **AI** | Machines imitating human cognitive functions (learning, problem-solving) |
| **Machine Learning** | Using statistical/mathematical techniques to build models from sample data for prediction/decision without explicit programming |
| **Deep Learning** | Multi-layer neural networks autonomously learning optimal task execution from large datasets |

**Hierarchy**: AI ⊃ Machine Learning ⊃ Deep Learning

### IoT Cloud Architecture

```
Sensors → IoT Device → Internet Access Device → Server → Database → Applications
```

- Sensor data collected automatically, accurately, in real-time
- Sent via Internet to server, stored in database
- Processed and delivered through applications as information/services

### AIoT Case Study: Weather Prediction System

1. **Sensor/Hub**: Periodically collect sensor values (temperature, humidity, rain sensor)
2. **Cloud Server**: Store sensor data to database
3. **Python Data Prep**: Missing value handling, smoothing
4. **Python Analytics**: Sliding window selects recent observations to train model (e.g., Decision Tree)
5. **Python Web Service**: Expose model as web service; input current temperature/humidity → predict rainfall

**Hardware example**: Raspberry Pi + DHT11 (temp/humidity) + MH-RD (rain) + LED indicators

### Generative AI in AIoT

| AIoT Function | LLM/LangChain Value |
|:---|:---|
| Sensor monitoring | Explain anomalies in natural language |
| Smart home/building control | Convert user intent to device actions |
| Predictive maintenance | Summarize sensor trends and recommend actions |
| Security monitoring | Generate alerts with explanations and escalation steps |
| Industrial IoT dashboards | Answer questions based on logs, manuals, and sensor history |
| Multi-device coordination | Use Agentic workflows to select tools/actions |

---

## Lecture 02 — Single-board Microcontroller (I)

### Microcontroller vs Single-board Computer

| Feature | Microcontroller | SBC |
|:---|:---|:---|
| **Interface** | None (GPIO/pins only) | Yes (keyboard, mouse, display) |
| **Computing** | Single program; even RTOS only supports concurrent tasks | Full OS; multiprogramming, multitasking, multithreading |
| **Examples** | micro:bit, Arduino UNO, D1 R32 | Raspberry Pi |

### micro:bit Technical Specifications

- **Size**: 4cm × 5cm (half credit card)
- **Processor**: 32-bit ARM Cortex-M0 CPU, 16MHz, 16K RAM
- **Connectivity**: micro-USB (wired), BLE (wireless), Radio 2.4GHz (wireless)
- **Input**: 2 programmable buttons (A/B), 25-pin edge connector (5 large + 20 small)
- **Output**: 25 independently programmable LEDs (5×5 matrix)
- **On-board sensors**: Accelerometer, compass/magnetometer, temperature, light sensor

### Programming Model

**Reactive System**: Continuously responds to external events (button press, shake, etc.). Requires responsiveness (timely reaction) and concurrency.

**Non-preemptive Multitasking**: Single CPU, one instruction at a time. Scheduler interrupts every **6ms**, polls inputs, triggers events. Subroutines must actively yield via `pause`/`sleep`. Uses **Round-robin scheduling**: Run Queue + Sleep Queue.

**Event-driven structure**:
- `on start`: Executes once at program start (like `main()`)
- `forever`: Infinite loop, runs in background, yields between iterations
- `on <event>`: Event handler, queued for execution when event fires

### Basic I/O & Sensors

**Input sources**: Buttons (A, B, A+B), gestures (shake, logo up/down, screen up/down, tilt left/right, free fall, 3g/6g/8g), pins (0, 1, 2: GPIO/ADC)

| Sensor Data | Description |
|:---|:---|
| `temperature` | Ambient temperature (°C) |
| `lightLevel` | Light intensity, 0 (dark) ~ 255 (bright) |
| `compassHeading` | Compass direction (degrees), requires calibration |
| `acceleration` | Linear acceleration (x, y, z), milli-gravity |
| `rotation` | Pitch/roll along x/y axes (degrees) |
| `magneticForce` | Magnetic force (micro-Teslas) |

**LED output**: `show number` / `show string` / `show icon`, `show LEDs` (custom 5×5), `plot bar graph`, `plot x y` / `unplot x y` / `toggle x y`

### Control Flow & Data Structures

- Conditionals: `if` / `if-else` / `if-else if-else`, relational operators (`==`, `!=`, `<`, `<=`, `>`, `>=`), logical operators (`&&`, `||`)
- Loops: `while`, `for`, `for...of`
- Functions: parameterized, reusable
- Arrays: zero-indexed, `push`/`pop` (end add/remove), `insertAt`/`removeAt` (specified position)

### Wireless Communication

**Radio (2.4GHz)**:
- Group ID: 0–255, same-group devices can communicate
- Transmission power: 0 (−30dBm) ~ 7 (+4dBm), max power range up to **70m** open area
- Data types: Number (32-bit signed int), String (max 19 chars), Name-Value Pair (Name max 8 chars)
- **Note**: Radio and BLE cannot run simultaneously
- Received packet properties: `time`, `serial`, `signal` (−128 ~ −42)

**BLE (Bluetooth Low Energy)**: Requires pairing. Supports multiple services (Button, LED, etc.). Bidirectional communication, but each service is unidirectional.

---

## Lecture 03 — Single-board Microcontroller (II)

### Basic Electronics

#### Breadboard
- Solderless prototyping board
- Top/Bottom rows (blue/red): horizontally connected (power rails)
- Middle columns: vertically connected per column, split by central gap

#### LED (Light Emitting Diode)
- **Anode** (longer leg): positive supply
- **Cathode** (shorter leg): ground (GND)
- Polarity matters; **always use a current-limiting resistor** (e.g., 330Ω)
- Resistor is non-polarized

#### Jumper Wires
| Type | Use Case |
|------|----------|
| Male-Female (M-F) | Pin → breadboard or socket |
| Male-Male (M-M) | Breadboard-to-breadboard |
| Female-Female (F-F) | Controller pin-to-pin (less common) |

### Micro:bit Pin Architecture

#### Large Pins (Edge Connector — Crocodile Clip Compatible)
| Pin | Function |
|-----|----------|
| **0, 1, 2** | GPIO + ADC (analogue input) + touch input |
| **3V** | 3V power output (or input) |
| **GND** | Ground reference |

#### Small Pins (Requires Breakout Board)
| Pin | Shared With | Notes |
|-----|-------------|-------|
| 3 | LED Col 1 | Available when LED screen off |
| 4 | LED Col 2 | Available when LED screen off |
| 5 | Button A | Built-in pull-up resistor |
| 6 | LED Col 9 | Digital I/O when screen off |
| 7 | LED Col 8 | Digital I/O when screen off |
| 8 | Dedicated GPIO | Pure digital |
| 9 | LED Col 7 | Digital I/O when screen off |
| 10 | LED Col 3 | Available when LED screen off |
| 11 | Button B | Built-in pull-up resistor |
| 12 | Dedicated GPIO | Also SPI Chip Select |
| 13 | SCK | SPI clock |
| 14 | MISO | SPI Master In Slave Out |
| 15 | MOSI | SPI Master Out Slave In |
| 16 | GPIO / SPI CS | Chip Select |
| 17–18 | 3V3 | Power |
| 19–20 | I2C (SCL, SDA) | Shared with internal accelerometer & compass |
| 21–22 | GND | Ground |

### Serial Communication

#### USB Serial
- micro:bit appears as USB Serial Device (COM port on Windows, `/dev/ttyACM0` on Linux)
- Default baud rate: **115200**
- Data types: `writeLine`, `writeNumber`, `writeValue` (key-value), `writeString`, `writeNumbers` (CSV array)

#### GPIO Serial (Peer-to-Peer)
- `serial.redirect(tx, rx, baudRate)` redirects serial to GPIO pins
- Cross-connect TX↔RX between two micro:bits + common GND

### GPIO Programming Experiments

- **External Buttons**: Connect between Pin 5 (or 11) and GND → triggers Button A (or B)
- **External LED**: Pin → LED anode → cathode → Resistor → GND. `digital write` (0/1), `analog write` (0–1023 PWM)
- **ADC**: 10-bit, 0V–3.3V → 0–1023. **Only Pins 0, 1, 2 support analogue input**

---

## Lecture 04 — Single-board Computer (I)

### Raspberry Pi Overview

| Model | Key Specs |
|-------|-----------|
| **Pi 3 Model B** | Quad Core 1.2GHz BCM2837, 1GB RAM, 40-pin GPIO, 4×USB 2.0, Wi-Fi, Bluetooth |
| **Pi 4 Model B** | Quad Core Cortex-A72 @1.5GHz, up to 8GB RAM, USB-C power, dual micro-HDMI (4K) |
| **Pi 5** | Quad Core Cortex-A76 @2.4GHz, up to 16GB RAM, 2–3× speed of Pi 4, dedicated I/O chip |

#### Key Interfaces
- **HDMI**: Display output
- **GPIO**: 40-pin header
- **USB/Ethernet**: Full computer peripherals
- **Micro SD**: OS storage (Raspberry Pi OS — Debian-based Linux)
- **CSI/DSI**: Camera and touchscreen display ports

### GPIO Programming (RPi.GPIO)

#### Pin Numbering Modes
| Mode | Description | Recommendation |
|------|-------------|----------------|
| `GPIO.BOARD` | Physical pin numbers (1–40) | **Recommended for beginners** |
| `GPIO.BCM` | Broadcom chip GPIO numbers | Requires pinout reference |

#### 40-Pin Header Functions
| Category | Pins | Description |
|----------|------|-------------|
| GPIO | Multiple | General purpose input/output |
| I2C | Pin 3 (SDA1), Pin 5 (SCL1) | I2C bus |
| SPI | Pin 19 (MOSI), 21 (MISO), 23 (SCLK) | SPI bus |
| UART | Pin 8 (TXD), 10 (RXD) | Serial communication |
| Power | Pin 1/17 (3.3V), Pin 2/4 (5V) | Power output |
| GND | Pin 6, 9, 14, 20, 25, 30, 34, 39 | Common ground |

> **Critical**: Pi GPIO logic level is **3.3V**. Do not apply 5V directly to GPIO pins.

#### LED Blinker Pattern
```python
import RPi.GPIO as GPIO
import time

ledPin = 11  # BOARD mode: physical pin 11 = GPIO 17
GPIO.setmode(GPIO.BOARD)
GPIO.setup(ledPin, GPIO.OUT)

try:
    for i in range(50):
        GPIO.output(ledPin, True)   # HIGH → LED on
        time.sleep(1)
        GPIO.output(ledPin, False)  # LOW → LED off
        time.sleep(1)
except KeyboardInterrupt:
    print("Terminated")
finally:
    GPIO.cleanup()  # Release pins
```

#### Push Button
```python
butPin = 12
GPIO.setup(butPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
# Button to GND → pin LOW when pressed
```
- **Pull-up/down resistors mandatory** to prevent floating pin states
- `GPIO.PUD_UP`: defaults HIGH, pressed → LOW (button to GND)
- `GPIO.PUD_DOWN`: defaults LOW, pressed → HIGH (button to 3.3V)

---

## Lecture 05 — Single-board Computer (II)

### Signal Edge Detection
- **Rising edge**: Low → High (0 → 1); **Falling edge**: High → Low (1 → 0)
- Used to digitize analogue signals (e.g., heart rate sensors)

#### Heart Rate Sensor (Grove Ear-clip PPG)
- **PPG (Photoplethysmography)**: Light-based blood volume measurement
- Each **rising edge = 1 heartbeat**
- `GPIO.add_event_detect(pin, GPIO.RISING, callback=handler)`

### Analogue Inputs (MCP3008 ADC)
- **Raspberry Pi has NO built-in ADC**
- MCP3008: 8 channels, SPI communication
- GPIO Zero: `from gpiozero import MCP3008` → `pot = MCP3008(channel=0)` reads 0.0–1.0

### PWM (Pulse-Width Modulation)
- Digital signal simulating analogue output via duty cycle
- 100% = fully on (3.3V), 0% = off, 50% = half brightness
- GPIO Zero: `PWMLED(pin)` + `led.source = pot.values`

### BME280 Environmental Sensor
- Temperature (±1.0°C), Barometric Pressure (±1 hPa), Humidity (±3%)
- I2C Wiring: VIN → 3.3V, GND → GND, SCK → Pin 5 (SCL), SDI → Pin 3 (SDA)
- Library: `adafruit-circuitpython-bme280`

### BLE on Raspberry Pi
#### GAP States
| State | Description |
|-------|-------------|
| Standby | Idle initial state |
| Advertiser | Broadcasting connectable advertisements |
| Scanner | Receiving advertisements |
| Initiator | Sending connection request |
| Slave/Master | Connected: advertiser=slave, initiator=master |

#### GATT Hierarchy
```
Service → Characteristic → Value / Properties / Descriptors
```

#### BlueZ Tools
- **BlueZ**: Official Linux Bluetooth stack
- **bluetoothctl**: Interactive scanning, pairing, connecting
- **gatttool**: Low-level GATT operations

### Micro:bit BLE Services

#### Temperature Service
| Type | UUID |
|------|------|
| Primary Service | `e95d6100-251d-470a-a062-fa1922dfa9a8` |
| Characteristic (Value) | `e95d9250-251d-470a-a062-fa1922dfa9a8` |
| Characteristic (Period) | `e95d1b25-251d-470a-a062-fa1922dfa9a8` |

#### Magnetometer Service
| Type | UUID |
|------|------|
| Primary Service | `e95df2d8-251d-470a-a062-fa1922dfa9a8` |
| Characteristic (Bearing) | `e95d9715-251d-470a-a062-fa1922dfa9a8` |
| Characteristic (Raw X/Y/Z) | `e95dfb11-251d-470a-a062-fa1922dfa9a8` |

#### UART Service
| Type | UUID |
|------|------|
| Primary Service | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` |
| TX (micro:bit → host) | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` |
| RX (host → micro:bit) | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` |

- Requires additional micro:bit code; 60-byte buffer, max 20 bytes per transmission
- Most flexible service: can send any custom data

### Advanced Interfaces
- **Serial over USB**: micro:bit → `/dev/ttyACM0`; pySerial for Python
- **Pi Camera**: `picamera` library; `sleep(2)` before capture for auto-exposure
- **PIR Motion Sensor**: 5V digital output, ~6m range, adjustable delay/sensitivity

---

## Lecture 06 — IoT Backend Integration

### IoT Protocol Landscape
| Dimension | BLE/Zigbee (Non-IP) | REST (HTTP) | MQTT |
|-----------|---------------------|-------------|------|
| Network | PAN (few nodes) | IP-based | IP-based |
| Data Nature | — | Document-centric (JSON) | Data-centric |
| Pattern | — | Request-Response | Publish-Subscribe |
| Complexity | — | More complex | Simple |
| Interaction | 1-to-1 | 1-to-1 | 1-to-1 & 1-to-many |

### RESTful Web Services

#### HTTP Verbs
| Verb | Action | CRUD |
|------|--------|------|
| GET | Read | R |
| POST | Create/Update | C/U |
| PUT | Create (idempotent) | C |
| DELETE | Delete | D |

#### Flask Basics
```python
from flask import Flask
app = Flask(__name__)

@app.route('/')
def index():
    return 'Hello World'

@app.route('/user/<username>')
def show_user(username):
    return f'User {username}'

@app.route('/post/<int:post_id>')
def show_post(post_id):
    return f'Post {post_id}'
```
- Converters: `string` (default), `int`, `float`, `path`, `uuid`
- Static files: `/static` folder; `url_for('static', filename='...')`
- Templates: Jinja2; `render_template('index.html', name=name)`
- Session: server-side on signed cookies; requires `SECRET_KEY`

#### Connexion + Swagger (OpenAPI)
```python
import connexion
app = connexion.App(__name__, specification_dir='./')
app.add_api('swagger.yml')
app.run(host='0.0.0.0', port=5000)
```
- `operationId` maps to Python function (e.g., `people.read` → `people.py` module `read()`)
- Swagger UI auto-generated at `/api/ui/`

#### Testing & Consumption
- Postman: custom headers, query params, JSON body
- Python `requests`: `requests.get()`, `.post()`, `.put()`, `.delete()`

### Database Integration
| Library | Purpose |
|---------|---------|
| MySQL Connector | Driver for MySQL |
| SQLAlchemy | ORM (Object-Relational Mapper) |
| SQLite (built-in) | Serverless, lightweight — **preferred on Pi** |

### MQTT (Message Queuing Telemetry Transport)
- **Publish-Subscribe**: Decoupled publishers and subscribers
- **Broker**: Central server routes messages
- **Topic**: Hierarchical string (e.g., `data/factory/floor/1/temperature`)

#### QoS Levels
| Level | Name | Behavior |
|-------|------|----------|
| 0 | At most once | Fire and forget |
| 1 | At least once | PUBACK acknowledgment |
| 2 | Exactly once | Four-way handshake, slowest but safest |

#### Python: Eclipse Paho
```python
import paho.mqtt.client as mqtt
client = mqtt.Client()
client.connect("broker.emqx.io", 1883, 60)
client.publish("/sws3025/lecture06", "temperature:25")
client.subscribe("/sws3025/lecture06")
```
- Public broker for testing: `broker.emqx.io`
- Production: Eclipse Mosquitto

### Temperature Monitoring Architecture
```
Micro:bit Nodes (temperature) → BLE → Raspberry Pi (Hub/Fog)
                                    ↓
                              RESTful API / MQTT
                                    ↓
                        Cloud Server (Laptop) + MySQL
                                    ↓
                              Third-party Apps
```

---

## Lecture 07 — IoT Data Preprocessing

### Machine Learning Overview

| Pattern | Type | Description | Example |
|---------|------|-------------|---------|
| **Prediction** | Supervised | Learn A→B mapping | Classification, Regression |
| **Classification** | Supervised | Predict discrete class label | Rain / No Rain |
| **Regression** | Supervised | Predict continuous value | Amount of rainfall (mm) |
| **Segmentation** | Unsupervised | Partition into natural groups | Clustering customers |
| **Association** | Unsupervised | Discover variable relationships | Market basket analysis |

- **Supervised**: Training data includes both input (A) and output/label (B)
- **Unsupervised**: Training data includes only input (A), no labels

### Python Data Science Stack
| Library | Purpose |
|---------|---------|
| **NumPy** | N-dimensional arrays, scientific computing |
| **Pandas** | Data structures & analysis (Series, DataFrame) |
| **Matplotlib** | 2D/3D plotting and visualization |
| **Scikit-Learn** | ML algorithms (classification, regression, clustering) |

### NumPy
- **ndarray**: Homogeneous array; attributes: `ndim`, `shape`, `size`, `dtype`
- Creation: `np.array([...])`, `np.arange(n)`, `np.zeros()`, `np.ones()`
- Operations: element-wise `+`, `*`, broadcasting; matrix: `np.dot(A, B)` or `A @ B`
- Indexing: zero-based, slicing `a[1:4]`, `A[0:2, 1:3]`

### Pandas
- **Series (1D)**: Labeled array; `pd.Series([...], index=[...])`; selection: `s['b']`, `s[s > 8]`
- **DataFrame (2D)**: Tabular data; row index + column index; creation from dict
- Selection: `df['col']`, `df.iloc[0]` (position), `df.loc['label']` (label)
- Operations: `df.describe()`, `df.sum()`, `df.mean()`
- I/O: `pd.read_csv('file.csv', index_col='id')`

### Matplotlib
- Three layers: Scripting (pyplot) → Artist (chart elements) → Backend (rendering)
- Key objects: Figure → Axes → Axis
- Pandas integration: `df.plot()`, `df.plot(kind='bar')`, `df.boxplot()`, `df.hist()`, `df.plot(kind='scatter')`
- **Box Plot**: Box = Q1–Q3, line = median, whiskers = range/1.5×IQR, dots = outliers

---

## Lecture 08 — Machine Learning for IoT Data (I)

### Data Mining Patterns
```
Data Mining
├── Prediction
│   ├── Classification
│   └── Regression
├── Segmentation (Clustering)
└── Association
```

### Regression Analysis

**Simple Linear Regression**: $Y = \alpha + \beta X + \varepsilon$
- $\alpha$: intercept; $\beta$: slope (marginal effect per unit $X$); $\varepsilon$: error term

**Multiple Linear Regression**: $Y = \alpha + \beta_1 X_1 + \beta_2 X_2 + \cdots + \beta_n X_n + \varepsilon$

**Evaluation Metrics**:
| Metric | Description | Criterion |
|:---|:---|:---|
| **F-statistic** | Overall model significance | p-value < 0.05 |
| **R²** | Proportion of variance explained | Closer to 1 = better |
| **Adjusted R²** | R² corrected for number of predictors | Close to R² = predictors useful |
| **RMSE** | $\sqrt{SSE/n}$ | Closer to 0 = better |
| **p-value (coefficient)** | Individual coefficient significance | < 0.05 to reject null |

**Five Assumptions**: Linearity, Homoscedasticity, Residual Normality, No Autocorrelation (Durbin-Watson $d \approx 2$), No Multicollinearity (VIF < 5)

**Multicollinearity**: $VIF_j = \frac{1}{1 - R_j^2}$; VIF > 5 → remove variable or use Ridge regression

### Classification Models Overview

**Three stages**: Training → Testing → Prediction

**Model Taxonomy**:
| Type | Algorithms | Characteristics |
|:---|:---|:---|
| **Heuristic** | Decision Tree, K-NN | Simple, distance/divide-and-conquer based |
| **Separation** | SVM, Perceptron, Neural Networks | Partition variable space into regions |
| **Regression** | Logistic Regression | Reformulate classification as linear regression |
| **Probabilistic** | Naive Bayes | Posterior probability via Bayes' theorem |

**Evaluation Methods**:
| Method | Description |
|:---|:---|
| **Holdout** | Train set (1/2–2/3) + test set |
| **Repeated Random Sampling** | Repeat holdout $r$ times, average accuracy |
| **Cross-validation (k-fold)** | $k$ subsets, rotate test set; typically $k=10$ |
| **Leave-One-Out** | $k=m$, each sample as test set; small datasets |
| **Stratified Sampling** | Maintain class proportions in train/test split |

**Confusion Matrix (Binary)**:
|  | Predicted Negative | Predicted Positive |
|:---|:---|:---|
| **Actual Negative** | TN ($p$) | FP ($q$) |
| **Actual Positive** | FN ($u$) | TP ($v$) |

- **Accuracy**: $\frac{p+v}{m}$
- **TPR (Recall)**: $\frac{v}{u+v}$
- **FPR**: $\frac{q}{p+q}$
- **Precision**: $\frac{v}{q+v}$
- **F-measure**: $F = \frac{(\beta^2+1) \cdot tp \cdot prc}{\beta^2 \cdot prc + tp}$
- **ROC Curve**: TPR vs FPR; AUC larger = better; ideal point (0, 1)

### Decision Trees

**Construction**: Recursive, heuristic, top-down induction
1. All observations in root node
2. Select optimal split based on impurity criterion
3. If node "pure" enough or stop condition met → leaf node (majority class)
4. Otherwise split, add children to active list, repeat

**Impurity Measures**:
| Measure | Formula | Max (binary) | Min |
|:---|:---|:---|:---|
| **Misclassification** | $1 - \max_h p_h$ | 0.5 | 0 |
| **Entropy** | $-\sum p_h \log_2 p_h$ | 1 | 0 |
| **Gini Index** | $1 - \sum p_h^2$ | 0.5 | 0 |

**Information Gain**: $\Delta = I(\text{parent}) - \sum \frac{Q_k}{Q} I(\text{child}_k)$ — choose split maximizing gain

**Pruning**: Pre-pruning (min instances threshold) or Post-pruning (remove branches to improve test accuracy)

> Scikit-learn `DecisionTreeClassifier` requires **One-Hot Encoding** for categorical variables.

---

## Lecture 09 — Machine Learning for IoT Data (II)

### Naive Bayes

**Bayes' Theorem**: $P(A|B) = \frac{P(B|A)P(A)}{P(B)}$

**MAP (Maximum A Posteriori)**: Compare $P(x|A)P(A)$ vs $P(x|B)P(B)$; denominator $P(x)$ cancels out.

**Naive assumption**: Given the target class, all explanatory variables are **conditionally independent**:
$$P(x|y) = P(x_1|y) \times P(x_2|y) \times \cdots \times P(x_n|y)$$

**Scikit-learn**: `MultinomialNB` (discrete), `BernoulliNB` (binary/boolean), `GaussianNB` (continuous, assumes normal distribution)

### Logistic Regression

**Sigmoid**: $p = \frac{1}{1 + e^{-(\beta_0 + \beta_1 X_1 + \cdots + \beta_n X_n)}}$ — maps linear combination to (0, 1)

**Odds & Logit**:
- odds = $\frac{p}{1-p} = e^{\beta_0 + \beta_1 X_1 + \cdots}$
- logit = $\ln(\frac{p}{1-p}) = \beta_0 + \beta_1 X_1 + \cdots$
- $e^{\beta_i}$: Odds Ratio — multiplier factor for odds when $X_i$ increases by 1
- $\beta_i > 0$: odds and probability increase with $X_i$

**vs Naive Bayes**: NB is **generative** (estimates $P(x|y)$ and $P(y)$); LR is **discriminative** (directly estimates $P(y|x)$)

### SVM (Support Vector Machines)

**Core idea**: Find **maximum margin** hyperplane separating classes.

- **Support Vectors**: Samples closest to decision boundary — determine the hyperplane
- **Kernel Trick**: Map data to higher-dimensional space for linear separability without explicit computation

| Kernel | Formula |
|:---|:---|
| **Gaussian RBF** | $\exp(-\gamma ||x - l||^2)$ |
| **Sigmoid** | $\tanh(\gamma \cdot X^T Y + r)$ |
| **Polynomial** | $(\gamma \cdot X^T Y + r)^d, \gamma > 0$ |

**Hyperparameters**:
| Parameter | Effect |
|:---|:---|
| **C (regularization)** | Large C: strict classification, overfit risk; Small C: larger margin, more tolerance |
| **Gamma** | High: only near points influence; Low: far points also influence boundary |

### Random Forest

**Core mechanisms**:
1. **Bagging (Bootstrap Aggregating)**: Random sampling with replacement, build multiple subsets
2. **Random feature selection**: At each node split, randomly select feature subset, pick best split from subset
3. **Aggregation**: Classification → majority vote; Regression → average

| Advantages | Disadvantages |
|:---|:---|
| Higher accuracy, lower overfitting | Higher computational cost |
| Robust to noise and outliers | Lower interpretability (ensemble) |
| Handles high-dimensional data | May still overfit with too many / undiversified trees |

### Artificial Neural Networks (ANN)

**Structure**: Input Layer → Hidden Layers (weights + biases + activation) → Output Layer

**Activation Functions**:
| Function | Formula | Use Case |
|:---|:---|:---|
| **ReLU** | $\max(0, x)$ | Hidden layer default, efficient |
| **Sigmoid** | $\frac{1}{1 + e^{-x}}$ | Binary output layer |
| **Softmax** | $\frac{e^{z_i}}{\sum e^{z_j}}$ | Multi-class output (sums to 1) |
| **Linear** | $f(x) = x$ | Regression output |

**Training**: Forward Propagation → Loss Calculation (MSE/Cross-entropy) → Backpropagation (chain rule) → Weight Update ($w_{new} = w_{old} - \alpha \cdot \nabla L$) → Iterate (epochs)

**Architecture Types**: FNN (regression/classification), CNN (images), RNN/LSTM (sequences), Transformer (attention), GAN (generation), Autoencoder (anomaly detection), GNN (graph data)

---

## Group Project Briefing

### Overview
- **Conceptualize, design and develop an AIoT project**
- Must demonstrate **both IoT and AI elements**
- Default group size: **4 students**
- Equipment collection: Wednesday, 15 July

### Equipment per Group
| Item | Qty |
|------|-----|
| Micro:bit v2 Board | 2 |
| ESP32 Board | 1 |
| Raspberry Pi 5 (8GB) | 1 |
| Sensor Kit | 1 |

### Deliverables
1. **IoT**: Prototype hardware collecting sensor data + actuation based on ML decisions
2. **AI**: Machine learning model analyzing sensor data
3. **SE**: Common backend with database + one or more frontend apps (web or mobile)

### Baseline Project
Weather Forecast AIoT Case Study (Lecture 06). Project complexity should be **at or above** this baseline.

### Proposal Requirements
1. Problem Description (organizational or consumer context)
2. Proposed Solution (IoT hardware, AI/ML approach, frontend design)
3. Additional Equipment List

### Key Dates
| Date | Milestone |
|------|-----------|
| 13 July (Mon) | Proposal submission |
| 15 July (Wed) | Equipment collection |
| 16 July (Thu) | Project consultation begins |
| 29 July | Project completion / final delivery |

---

## Cross-Lecture Concept Map

```
L01: AIoT Concepts, Cloud Architecture, Weather Case Study
  ↓
L02: micro:bit Basics (reactive system, sensors, radio/BLE, programming model)
  ↓
L03: micro:bit GPIO (digital/analogue, serial, edge connector, ADC)
  ↓
L04: Raspberry Pi GPIO (Python, RPi.GPIO, digital I/O, pull-up/down)
  ↓
L05: Pi Advanced (ADC via MCP3008, PWM, BLE, BME280, camera, PIR)
  ↓
L06: Backend (Flask REST API, Swagger, MQTT, SQLite, cloud/fog/hub)
  ↓
L07: Data Science (NumPy, Pandas, Matplotlib, Scikit-Learn intro)
  ↓
L08: ML I (Regression, Classification overview, Decision Trees, evaluation metrics)
  ↓
L09: ML II (Naive Bayes, Logistic Regression, SVM, Random Forest, Neural Networks)
  ↓
PROJECT: End-to-end AIoT system integrating all layers
```

### Communication Stack Summary
| Layer | Protocol | Hardware |
|-------|----------|----------|
| Edge ↔ Hub | BLE / Radio / Serial USB | Micro:bit ↔ Raspberry Pi |
| Hub ↔ Cloud | REST (HTTP) / MQTT | Raspberry Pi ↔ Laptop/Server |
| Cloud ↔ Frontend | REST (HTTP) / WebSocket | Server ↔ Browser/App |
| Data Format | JSON / CSV | — |

---

## Appendix: Quick Reference Formulas

### Statistics & Regression
- $R^2 = 1 - \frac{SSE}{SST}$
- $RMSE = \sqrt{\frac{SSE}{n}}$
- $VIF_j = \frac{1}{1 - R_j^2}$
- Durbin-Watson: $d \approx 2$ → no autocorrelation

### Bayes
- $P(y|x) = \frac{P(x|y)P(y)}{\sum_{l=1}^H P(x|y_l)P(y_l)}$

### Logistic
- $p = \frac{1}{1 + e^{-z}}$, $z = \beta_0 + \beta_1 X_1 + \cdots + \beta_n X_n$

### Decision Tree Impurity
- Gini: $1 - \sum p_h^2$
- Entropy: $-\sum p_h \log_2 p_h$
- Information Gain: $I(parent) - \sum \frac{Q_k}{Q} I(child_k)$

### SVM Kernels
- RBF: $\exp(-\gamma ||x - l||^2)$
- Polynomial: $(\gamma \cdot X^T Y + r)^d$

### Neural Networks
- ReLU: $\max(0, x)$
- Softmax: $\frac{e^{z_i}}{\sum e^{z_j}}$
- Weight update: $w_{new} = w_{old} - \alpha \cdot \nabla L$

---

*End of complete course reference. Ready for AIoT project development.*
