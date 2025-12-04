# 🛍️ Telegram Shop Bot

A production-ready Telegram shop bot with advanced security features, transactional integrity, comprehensive admin
tools, real-time monitoring, and disaster recovery capabilities.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Aiogram](https://img.shields.io/badge/aiogram-3.22+-green.svg)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 🔀 Looking for Physical Goods Shop?

**📦 This version is for DIGITAL GOODS** (accounts, keys, licenses, etc.)

**💾 Need to sell PHYSICAL GOODS instead?** (if you need functions such as inventory, shipping, delivery addresses, etc.)
👉 **Try this new version**: [Telegram Physical Goods Shop](https://github.com/interlumpen/Telegram-shop-Physical)

The physical goods version features a well-thought-out delivery processing system, full interaction with the bot's core via the command line (CLI) without the need for a shell and advanced monitoring of all processes.

---

## 🎬 Demo

<div align="center">
  <img src="assets/admin_pov.gif" alt="Admin Interface" width="400"/>
  <img src="assets/user_pov.gif" alt="User Interface" width="400"/>
</div>

## 📋 Table of Contents

- [Features](#-features)
- [Security](#-security)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Environment Variables](#-environment-variables)
- [Installation](#-installation)
- [Monitoring & Metrics](#-monitoring--metrics)
- [Usage](#-usage)
- [API Documentation](#-api-documentation)
- [Testing](#-testing)
- [Contributing](#-contributing)
- [License](#-license)

## ✨ Features

### Core Shop Functionality

- **Product Management**: Categories, items with stock tracking
- **Transactional Purchases**: ACID-compliant purchase process
- **Multiple Payment Methods**:
    - 💎 CryptoPay (TON, USDT, BTC, ETH)
    - ⭐ Telegram Stars
    - 💳 Telegram Payments (Fiat)
- **Referral System**: Configurable commission rates
- **Multi-language Support**: Russian and English localization

### Admin Features

- **Role-Based Access Control** (RBAC):
    - USER: Basic shop access
    - ADMIN: Shop management + user management
    - OWNER: Full control including admin management
- **Comprehensive Admin Panel**:
    - Real-time statistics dashboard
    - User management with balance control
    - Product and category management
    - Broadcast messaging system
    - Audit logging with rotation

### User Experience

- **Lazy Loading Pagination**: Efficient data loading for large catalogs
- **Purchase History**: Complete transaction records
- **Referral Dashboard**: Track earnings and referrals
- **Channel Integration**: Optional news channel with subscription checks

### Performance & Reliability

- **Advanced Connection Pooling**: Optimized PostgreSQL connection management with QueuePool
    - 20 persistent connections with up to 40 overflow connections
    - Automatic connection recycling and timeout handling
    - Graceful handling of high-load scenarios
- **Intelligent Redis Caching**: Multi-layer caching system for optimal performance
    - User role caching (15-minute TTL)
    - Product catalog caching (5-minute TTL)
    - Statistics caching (1-minute TTL)
    - Smart cache invalidation on data updates
- **Performance Optimizations**: Up to 60% reduction in database queries for read operations

### Monitoring & Analytics

- **Real-Time Metrics Collection**:
    - Event tracking (purchases, payments, user actions)
    - Performance metrics (response times, query durations)
    - Error tracking and categorization
    - Conversion funnel analysis
- **Web-Based Monitoring Dashboard**:
    - Interactive UI at `/dashboard`
    - Live statistics and system health
    - Error tracking and analysis
    - Performance visualization
- **Prometheus-Compatible Metrics**:
    - Export endpoint at `/metrics/prometheus`
    - Ready for integration with Grafana
    - Custom metrics for business KPIs
- **Health Check Endpoint**:
    - System status at `/health`
    - Database connectivity check
    - Redis status monitoring
    - Bot API availability

### Disaster Recovery System

- **Automatic Recovery Manager**:
    - Pending payment recovery
    - Interrupted broadcast resumption
    - Failed transaction rollback
    - Connection pool recovery
- **State Persistence**:
    - Critical state saving to disk
    - Recovery checkpoint creation
    - Graceful shutdown handling
- **Health Monitoring**:
    - Periodic system health checks
    - Automatic component restart
    - Dead connection detection
    - Resource leak prevention
- **Payment Recovery**:
    - Automatic check for stuck payments
    - Idempotent payment processing
    - User notification on recovery

## 🔒 Security

### Implemented Security Measures

#### 1. **Rate Limiting**

- Global limits: 30 requests per 60 seconds
- Action-specific limits:
    - Purchases: 5 per minute
    - Payments: 10 per minute
    - Broadcasts: 1 per hour
- Automatic ban system with configurable duration
- Admin bypass option

#### 2. **Security Middleware**

- **SQL Injection Protection**: Input validation and parameterized queries
- **XSS Prevention**: HTML sanitization for all user inputs
- **CSRF Protection**: Token validation for critical operations
- **Replay Attack Prevention**: Timestamp validation on callbacks

#### 3. **Authentication & Authorization**

- Bot detection and blocking
- Session-based authentication with TTL
- Permission-based access control
- Role caching for performance

#### 4. **Payment Security**

- **Idempotent Payment Processing**: Prevents duplicate charges
- **Transactional Integrity**: ACID compliance for all financial operations
- **External ID Tracking**: Unique identifiers for payment reconciliation

#### 5. **Data Validation**

- Pydantic models for request validation
- Decimal precision for monetary calculations
- Input sanitization for all text fields
- File size and type restrictions

## 🏗️ Architecture

### System Architecture

<details>
<summary>System Architecture Schema (click to expand)</summary>

![System Architecture](assets/system_architecture.png)
</details>

### Database Schema

<details>
<summary>Database Schema (click to expand)</summary>

![Database Schema](assets/database_schema.png)
</details>


- **Users**: Telegram ID, balance, referral tracking
- **Roles**: Permission-based access control
- **Products**: Categories, items, stock management
- **Transactions**: Purchases, payments, operations
- **Referrals**: Earnings tracking and statistics

### Key Design Patterns

- **Singleton**: Database connection management
- **Repository Pattern**: Data access layer
- **Middleware Pipeline**: Request processing chain
- **State Pattern**: FSM for multi-step processes
- **Transaction Script**: Business logic encapsulation
- **Observer Pattern**: Metrics collection and event tracking

### Performance Architecture

- **Connection Pooling**: Advanced PostgreSQL connection management with automatic recycling
- **Multi-Level Caching**: Redis-based intelligent caching with TTL-based expiration
- **Cache Invalidation**: Smart cache clearing on data modifications
- **Concurrent Load Handling**: Optimized for high-traffic scenarios with connection queuing
- **Metrics Pipeline**: Asynchronous metrics collection without performance impact

## 💻 Tech Stack

### Core

- **Language**: Python 3.11+
- **Framework**: Aiogram 3.22+ (async Telegram Bot API)
- **Database**: PostgreSQL 16+ with SQLAlchemy 2.0
- **Cache/Storage**: Redis 7+ (FSM states, rate limiting, intelligent data caching)
- **Migrations**: Alembic

### Security & Validation

- **Input Validation**: Pydantic
- **Rate Limiting**: Custom middleware with Redis
- **Authentication**: HMAC-based token system
- **Password Hashing**: hashlib with salting

### Payment Integrations

- **CryptoPay API**: Cryptocurrency payments
- **Telegram Stars API**: Native digital currency
- **Telegram Payments API**: Traditional payment providers

### Monitoring & Analytics

- **Metrics Collection**: Custom MetricsCollector with event tracking
- **Web Server**: aiohttp for monitoring dashboard
- **Export Formats**: JSON, Prometheus metrics format
- **Visualization**: Built-in HTML/CSS dashboard

### DevOps

- **Containerization**: Docker & Docker Compose
- **Logging**: Rotating file handlers with audit trails
- **Testing**: Pytest with async support
- **CI/CD Ready**: Environment-based configuration
- **Health Checks**: Built-in health monitoring endpoints

## ⚙️ Environment Variables

The application requires the following environment variables:

<details>
<summary><b>🤖 Telegram</b></summary>

| Variable   | Description                                                | Required |
|------------|------------------------------------------------------------|----------|
| `TOKEN`    | [Bot Token from @BotFather](https://telegram.me/BotFather) | ✅        |
| `OWNER_ID` | [Your Telegram ID](https://telegram.me/myidbot)            | ✅        |

</details>

<details>
<summary><b>💳 Payments</b></summary>

| Variable                  | Description                                                                                  | Default |
|---------------------------|----------------------------------------------------------------------------------------------|---------|
| `TELEGRAM_PROVIDER_TOKEN` | [Token for Telegram Payments](https://core.telegram.org/bots/payments#getting-a-token)       | -       |
| `CRYPTO_PAY_TOKEN`        | [CryptoPay API token](https://help.send.tg/en/articles/10279948-crypto-pay-api#h_020215e6d7) | -       |
| `STARS_PER_VALUE`         | Stars exchange rate (0 to disable)                                                           | `0.91`  |
| `PAY_CURRENCY`            | Display currency (RUB, USD, EUR, etc.)                                                       | `RUB`   |
| `REFERRAL_PERCENT`        | Referral commission percentage                                                               | `0`     |
| `PAYMENT_TIME`            | Invoice validity in seconds                                                                  | `1800`  |
| `MIN_AMOUNT`              | Minimum payment amount                                                                       | `20`    |
| `MAX_AMOUNT`              | Maximum payment amount                                                                       | `10000` |

</details>

<details>
<summary><b>🔗 Links / UI</b></summary>

| Variable      | Description                              | Default |
|---------------|------------------------------------------|---------|
| `CHANNEL_URL` | News channel link (public channels only) | -       |
| `HELPER_ID`   | Support user Telegram ID                 | -       |
| `RULES`       | Bot usage rules text                     | -       |

</details>

<details>
<summary><b>🌐 Locale & Logs</b></summary>

| Variable        | Description                   | Default     |
|-----------------|-------------------------------|-------------|
| `BOT_LOCALE`    | Localization language (ru/en) | `ru`        |
| `BOT_LOGFILE`   | Path to main log file         | `bot.log`   |
| `BOT_AUDITFILE` | Path to audit log file        | `audit.log` |
| `LOG_TO_STDOUT` | Console logging (1/0)         | `1`         |
| `LOG_TO_FILE`   | File logging (1/0)            | `1`         |
| `DEBUG`         | Debug mode (1/0)              | `0`         |

</details>

<details>
<summary><b>📊 Monitoring</b></summary>

| Variable          | Description                    | Default     |
|-------------------|--------------------------------|-------------|
| `MONITORING_HOST` | Monitoring server bind address | `localhost` |
| `MONITORING_PORT` | Monitoring server port         | `9090`      |

**Note**: When running in Docker, set `MONITORING_HOST=0.0.0.0` to allow external access.

</details>

<details>
<summary><b>📦 Redis Storage</b></summary>

| Variable         | Description                 | Default |
|------------------|-----------------------------|---------|
| `REDIS_HOST`     | Redis server address        | `redis` |
| `REDIS_PORT`     | Redis server port           | `6379`  |
| `REDIS_DB`       | Redis database number       | `0`     |
| `REDIS_PASSWORD` | Redis password (if enabled) | -       |

</details>

<details>
<summary><b>🗄️ Database (Docker)</b></summary>

| Variable            | Description              | Default               |
|---------------------|--------------------------|-----------------------|
| `POSTGRES_DB`       | PostgreSQL database name | **Required**          |
| `POSTGRES_USER`     | PostgreSQL username      | `postgres`            |
| `POSTGRES_PASSWORD` | PostgreSQL password      | **Required**          |
| `DB_PORT`           | PostgreSQL port          | `5432`                |
| `DB_DRIVER`         | Database driver          | `postgresql+psycopg2` |

</details>

<details>
<summary><b>🗄️ Database (Manual Deploy)</b></summary>

For manual deployment, configure `DATABASE_URL` in `bot/misc/env.py`:

```python
DATABASE_URL = "postgresql+psycopg2://user:password@localhost:5432/db_name"
```

[SQLAlchemy Documentation](https://docs.sqlalchemy.org/en/20/core/engines.html#postgresql)

</details>

## 📦 Installation

### Prerequisites

- Docker and Docker Compose (recommended)
- OR Python 3.11+ and PostgreSQL 16+

### 🐳 Deploy with Docker (Recommended)

1. **Clone the repository**

```bash
git clone https://github.com/interlumpen/Telegram-shop.git
cd Telegram-shop
```

2. **Create environment file**

```bash
cp .env.example .env
# Edit .env with your configuration
nano .env  # or use any text editor
```

3. **Start the bot**

```bash
docker compose up -d --build bot
```

The bot will automatically:

- Create database schema
- Apply all migrations
- Initialize roles and permissions
- Start accepting messages
- Launch monitoring dashboard on port 9090
- Initialize recovery systems

4. **View logs** (optional)

```bash
docker compose logs -f bot
```

5. Access monitoring dashboard

Open in browser: http://localhost:9090/dashboard

### 🔧 Manual Deployment

1. **Clone the repository**

```bash
git clone https://github.com/interlumpen/Telegram-shop.git
cd telegram-shop-bot
```

2. **Create virtual environment**

```bash
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

4. **Set up PostgreSQL**

```bash
# Create database (adjust credentials as needed)
createdb telegram_shop
createuser shop_user -P
```

5. **Configure environment**
    - [Set environment variables in PyCharm](https://stackoverflow.com/questions/42708389/how-to-set-environment-variables-in-pycharm)
    - Or export them in terminal:

```bash
export TOKEN="your_bot_token"
export OWNER_ID="your_telegram_id"
export POSTGRES_DB="telegram_shop"
export POSTGRES_USER="shop_user"
export POSTGRES_PASSWORD="your_password"
# Set other required variables
```

6. **Update DATABASE_URL** in `bot/misc/env.py`:

```python
DATABASE_URL = "postgresql+psycopg2://shop_user:your_password@localhost:5432/telegram_shop"
```

7. **Run migrations**

```bash
alembic upgrade head
```

8. **Start the bot**

```bash
python run.py
```

9. Access monitoring (optional)

Open in browser: http://localhost:9090/

### 📝 Post-Installation

1. **Add bot to channel** (if using news channel feature):
    - Add your bot to the channel specified in `CHANNEL_URL`
    - Grant administrator rights with "Post Messages" permission

2. **Apply latest migrations** (if updating):

```bash
# With Docker
docker compose run --rm bot alembic upgrade head

# Manual deployment
alembic upgrade head
```

3. **Verify installation**:
    - Send `/start` to your bot
    - Check that main menu appears
    - Access admin panel (owner only initially)
    - Check monitoring dashboard at http://localhost:9090/

## 📊 Monitoring & Metrics

### Dashboard Overview

The bot includes a comprehensive web-based monitoring system accessible at http://localhost:9090/

#### Available Endpoints

- / - Overview page with system status
- /dashboard - Real-time metrics dashboard
- /events - Event tracking and statistics
- /performance - Performance metrics and timing analysis
- /errors - Error tracking and debugging
- /metrics - Raw metrics in JSON format
- /metrics/prometheus - Prometheus-compatible metrics export
- /health - Health check endpoint for monitoring tools

### Recovery System

The bot includes an automatic disaster recovery system that handles:

#### Payment Recovery

- Checks for stuck payments every 5 minutes
- Automatically processes confirmed but uncredited payments
- Notifies users when recovery succeeds

#### Broadcast Recovery

- Saves broadcast state during execution
- Resumes interrupted broadcasts on restart
- Tracks delivery statistics

#### Health Monitoring

- Periodic checks of all system components
- Automatic restart of failed services
- Connection pool health verification
- Memory leak detection

#### State Persistence

- Critical state saved to data/ directory
- Automatic backup before shutdown
- Recovery checkpoints during long operations

## 📱 Usage

### User Interface

<details>
<summary>👤 User Features (click to expand)</summary>

#### Main Navigation

- `/start` - Initialize bot and show main menu
- Shop navigation via inline keyboard
- Quick access to all features

#### Main Menu

![Main Menu](assets/menu_picture.png)

#### Shop Categories

![Categories](assets/categories_picture.png)

#### Shop Goods

![Goods](assets/positions_picture.png)

#### Shop Item Information

![Item Information](assets/position_description_picture.png)

#### Profile

![Profile](assets/user_profile.png)

#### Purchases

![Purchases](assets/user_purchases.png)

#### Referral System

![Referral system](assets/referral_system.png)

</details>

### Admin Panel

<details>
<summary>🎛️ Admin Features (click to expand)</summary>

Available for users with ADMIN/OWNER role:

#### Admin Panel

![Admin Panel](assets/admin_menu_picture.png)

#### Shop Management

![Products](assets/shop_menu_picture.png)

#### Categories & Items  Management

- Categories, products, stock control

![Categories](assets/categories_management_menu_picture.png)
![Products](assets/goods_management_menu_picture.png)

#### User Management

- View profiles, adjust balances, change roles

![User Management](assets/user_menu_picture.png)

#### Broadcasting & Analytics

![Broadcast](assets/broadcast_picture.png)
![Statistics](assets/shop_statistics.png)

#### System Monitoring

![Logs](assets/bot_logs.png)

</details>

### Example Workflows

#### Adding a Product (Admin)

1. Admin Panel → Goods Management
2. Add Position → Enter name, description, price
3. Select category → Choose stock type (limited/unlimited)
4. Add stock values

#### Making a Purchase (User)

1. Shop → Select Category → Choose Product
2. Click Buy → Confirm purchase
3. Receive product details instantly

#### Processing Payment

1. Profile → Top up balance
2. Enter amount → Choose payment method
3. Complete payment → Balance credited automatically

## 📊 API Documentation

### Core Database Methods

#### User Management

```python
create_user(telegram_id: int, registration_date: datetime, referral_id: int, role: int) -> None
check_user(telegram_id: int) -> Optional[User]
update_balance(telegram_id: int, amount: int) -> None
```

#### Transaction Processing

```python
buy_item_transaction(telegram_id: int, item_name: str) -> tuple[bool, str, dict]
process_payment_with_referral(user_id: int, amount: Decimal, provider: str, external_id: str) -> tuple[bool, str]
```

#### Product Management

```python
create_item(item_name: str, item_description: str, item_price: int, category_name: str) -> None
add_values_to_item(item_name: str, value: str, is_infinity: bool) -> bool
delete_item(item_name: str) -> None
```

### Middleware Configuration

```python
# Rate limiting
RateLimitConfig(
    global_limit=30,
    global_window=60,
    action_limits={'buy_item': (5, 60)},
    ban_duration=300
)

# Security layers
SecurityMiddleware(secret_key="...")
AuthenticationMiddleware()
```

### Metrics Collection

```python
# Track custom events
metrics.track_event("purchase", user_id, metadata={"item": item_name})
metrics.track_timing("database_query", duration_ms)
metrics.track_conversion("purchase_funnel", "view_item", user_id)

# Get metrics summary
summary = metrics.get_metrics_summary()
prometheus_format = await metrics.export_to_prometheus()
```

### Recovery Management

```python
# Initialize recovery manager
recovery_manager = RecoveryManager(bot)
await recovery_manager.start()

# Manual recovery trigger
await recovery_manager.recover_pending_payments()
await recovery_manager.recover_interrupted_broadcasts()
```

### Caching & Performance

```python
# Cache configuration examples
@cache_result(ttl=900, key_prefix="user_roles")  # 15 minutes
async def get_user_role(telegram_id: int) -> str


@cache_result(ttl=300, key_prefix="catalog")  # 5 minutes  
async def get_products_by_category(category_id: int) -> List[Product]


# Cache invalidation
await invalidate_user_cache(telegram_id)
await invalidate_item_cache(item_name)
```

### Connection Pool Configuration

```python
engine = create_engine(
    DATABASE_URL,
    pool_size=20,  # Base pool size
    max_overflow=40,  # Additional connections during peaks
    pool_recycle=3600,  # Refresh connections every hour
    pool_timeout=30  # Max wait time for connection
)
```

## 🧪 Testing

The project includes a comprehensive test suite with **200 tests** covering all major components and edge cases.

### Running Tests

```bash
# Run all tests with verbose output
pytest tests/ -v --asyncio-mode=auto

# Run specific test modules
pytest tests/test_cache.py -v
pytest tests/test_payment.py -v
pytest tests/test_recovery_monitoring.py -v

# Run with coverage report
pytest tests/ --cov=bot --cov-report=html
```

### Test Modules Overview

| Module                        | Tests   | Coverage                       |
|-------------------------------|---------|--------------------------------|
| `test_broadcast.py`           | 4       | Broadcast messaging system     |
| `test_cache.py`               | 30      | Advanced caching mechanisms    |
| `test_database.py`            | 9       | Database operations & CRUD     |
| `test_fixes.py`               | 7       | Security & performance fixes   |
| `test_handlers.py`            | 14      | User interaction workflows     |
| `test_keyboards.py`           | 12      | UI keyboard generation         |
| `test_metrics.py`             | 18      | Analytics & monitoring         |
| `test_middleware.py`          | 14      | Security & rate limiting       |
| `test_paginator.py`           | 14      | Lazy loading pagination        |
| `test_payment.py`             | 14      | Multi-provider payments        |
| `test_recovery_monitoring.py` | 54      | Disaster recovery & monitoring |
| `test_validators.py`          | 10      | Data validation & security     |
| **Total**                     | **200** | **Complete system coverage**   |

The test suite validates:

<details>
<summary>Core Functionality</summary>

* ✅ **Transactional purchase safety** - Ensures only one user can buy the last item in stock
* ✅ **Payment idempotency** - Prevents duplicate payment processing
* ✅ **Referral system** - Tests referral earnings calculation and distribution

</details>

<details>
<summary>Security & Middleware</summary>

### Security & Middleware

* ✅ **Rate limiting** - Tests global and action-specific request limits
* ✅ **Security middleware** - Validates CSRF protection, SQL injection prevention, and XSS filtering
* ✅ **Authentication middleware** - Tests user authentication, role-based access control, and admin caching

</details>

<details>
<summary>Database Operations</summary>

* ✅ **CRUD operations** - Complete testing of Create, Read, Update, Delete for all models
* ✅ **Transaction rollback** - Ensures data integrity on errors
* ✅ **Concurrent access** - Tests database handling under concurrent load
* ✅ **Referral earnings tracking** - Validates proper referral bonus calculations

</details>

<details>
<summary>Communication Systems</summary>

* ✅ **Broadcast system** - Tests batch messaging with failure handling
* ✅ **Progress tracking** - Validates real-time broadcast progress updates
* ✅ **Cancellation support** - Tests ability to stop ongoing broadcasts

</details>

<details>
<summary>User Interface</summary>

* ✅ **Keyboard generation** - Tests all inline keyboard types and configurations
* ✅ **Lazy pagination** - Tests on-demand data loading with caching
* ✅ **Navigation controls** - Validates page navigation and back buttons
* ✅ **Payment keyboards** - Tests payment method selection and confirmation

</details>


<details>
<summary>Data Validation</summary>

* ✅ **Input sanitization** - Tests HTML escaping and dangerous pattern detection
* ✅ **Payment validation** - Validates amount ranges and currency formats
* ✅ **Item purchase validation** - Tests SQL injection and XSS prevention
* ✅ **Broadcast message validation** - Ensures HTML tag balancing and length limits
* ✅ **Search query sanitization** - Tests special character filtering

</details>

<details>
<summary>Performance Features</summary>

* ✅ **Caching mechanisms** - Tests page and admin role caching
* ✅ **Cache eviction** - Validates intelligent cache management
* ✅ **Batch processing** - Tests efficient message batching in broadcasts
* ✅ **State serialization** - Validates FSM state persistence and restoration

</details>

<details>
<summary>Advanced Caching System</summary>

* ✅ **Cache serialization** - Tests JSON/pickle fallback chains and complex data types
* ✅ **Cache invalidation** - Validates pattern-based cache clearing and error handling
* ✅ **Decorator functionality** - Tests cache_result decorator with custom key functions
* ✅ **Performance optimization** - Validates cache hit/miss tracking and TTL management
* ✅ **Integration testing** - Tests real-world caching scenarios with complex objects

</details>

<details>
<summary>Handler & Workflow Testing</summary>

* ✅ **Start handler flows** - Tests new user registration, referral handling, and channel subscription
* ✅ **Payment workflows** - Validates balance top-up, payment method selection, and amount validation
* ✅ **Admin navigation** - Tests role-based access to admin panels and features
* ✅ **State management** - Validates FSM state transitions and data persistence
* ✅ **Integration flows** - Tests complete user journeys from start to purchase

</details>

<details>
<summary>Metrics & Analytics System</summary>

* ✅ **Event tracking** - Tests user action tracking, timing measurements, and conversion funnels
* ✅ **Middleware analytics** - Validates automatic event collection and performance monitoring
* ✅ **Prometheus export** - Tests metrics formatting for external monitoring systems
* ✅ **Error categorization** - Validates error tracking and debugging information collection
* ✅ **Real-time dashboards** - Tests metrics summary generation and visualization data

</details>

<details>
<summary>Payment Processing System</summary>

* ✅ **Multi-provider support** - Tests Telegram Stars, CryptoPay, and fiat payment methods
* ✅ **Currency conversion** - Validates exchange rate calculations and rounding behavior
* ✅ **API integration** - Tests aiohttp async context managers and error handling
* ✅ **Method routing** - Validates GET/POST request handling for different API endpoints
* ✅ **Async mocking** - Tests complex async payment workflows with proper mock patterns

</details>

<details>
<summary>Disaster Recovery & Monitoring</summary>

* ✅ **Recovery manager** - Tests automatic payment recovery, broadcast resumption, and health monitoring
* ✅ **State persistence** - Validates critical state saving and restoration mechanisms
* ✅ **Health checks** - Tests periodic system health validation and component monitoring
* ✅ **Monitoring server** - Validates web dashboard, metrics endpoints, and real-time updates
* ✅ **Error recovery** - Tests graceful handling of database failures and connection issues

</details>

<details>
<summary>Edge Cases & Error Handling</summary>

* ✅ **Empty data handling** - Tests behavior with no results
* ✅ **Boundary conditions** - Tests pagination limits and partial pages
* ✅ **Error recovery** - Tests graceful handling of database and API errors
* ✅ **Timeout handling** - Tests behavior under network delays
* ✅ **Async pattern mocking** - Tests complex async/await patterns with proper coroutine handling

</details>

### Test Quality Features

- **Async Testing**: Full asyncio support with proper event loop handling
- **Mock Strategies**: Advanced mocking patterns for aiohttp, Redis, and database operations
- **Edge Case Coverage**: Comprehensive boundary condition and error scenario testing
- **Integration Testing**: End-to-end workflow validation
- **Performance Testing**: Concurrent access and load testing scenarios
- **Security Validation**: SQL injection, XSS, and CSRF protection testing

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guide
- Add tests for new features
- Update documentation
- Use type hints
- Write meaningful commit messages

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Aiogram](https://github.com/aiogram/aiogram) - Telegram Bot framework
- [SQLAlchemy](https://www.sqlalchemy.org/) - Database ORM
- [Redis](https://redis.io/) - Cache and storage
- Contributors and testers

## 📞 Support

- Create an [Issue](https://github.com/interlumpen/Telegram-shop/issues) for bug reports
