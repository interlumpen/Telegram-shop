# 🛍️ Telegram Shop Bot

A production-ready Telegram shop bot with advanced security features, transactional integrity, and comprehensive admin
tools.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Aiogram](https://img.shields.io/badge/aiogram-3.22+-green.svg)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

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

![System Architecture](assets/system_architecture.png)

### Database Schema

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

## 💻 Tech Stack

### Core

- **Language**: Python 3.11+
- **Framework**: Aiogram 3.22+ (async Telegram Bot API)
- **Database**: PostgreSQL 16+ with SQLAlchemy 2.0
- **Cache/Storage**: Redis 7+ (FSM states, rate limiting)
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

### DevOps

- **Containerization**: Docker & Docker Compose
- **Logging**: Rotating file handlers with audit trails
- **Testing**: Pytest with async support
- **CI/CD Ready**: Environment-based configuration

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

4. **View logs** (optional)

```bash
docker compose logs -f bot
```

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

## 🧪 Testing

Run the comprehensive test suite:

```bash
pytest tests/ -v --asyncio-mode=auto
```

The project includes comprehensive test coverage for all major components:

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
<summary>Edge Cases & Error Handling</summary>

* ✅ **Empty data handling** - Tests behavior with no results
* ✅ **Boundary conditions** - Tests pagination limits and partial pages
* ✅ **Error recovery** - Tests graceful handling of database and API errors
* ✅ **Timeout handling** - Tests behavior under network delays

</details>

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
