# Telegram shop

This is an example Telegram shop bot.
this is a fairly simple template, but at the same time it is quite effective for selling something directly in the
telegram

## Example:

### admin pov

![](assets/admin_pov.gif)

### user pov

![](assets/user_pov.gif)

## What can it do?

- `/start` - needed to start the bot

### Menu

the menu for the user looks like this:

![](assets/menu_picture.png)

The administrator has an "admin panel" button in the menu:

![](assets/menu_as_admin_picture.png)

### Referral system

The bot has a customizable referral system:

![](assets/referral_system.png)

### Catalog

The catalog consists of categories and positions. The user can buy goods from the positions, and the administrator can
manage them  
![](assets/categories_picture.png)

![](assets/positions_picture.png)

![](assets/position_description_picture.png)

### Admin panel

There are a couple of buttons in the admin panel to control all processes in the bot.

![](assets/admin_menu_picture.png)

![](assets/shop_menu_picture.png)

![](assets/goods_management_menu_picture.png)

If you have set up a channel, then after adding products, notifications about assortment updates will occur in it.
![](assets/assortment_update.png)

![](assets/categories_management_menu_picture.png)

![](assets/user_menu_picture.png)

### Other

The bot has configured logging that reports errors or actions of administrators

## Tech Stack 💻

- #### Languages:
    - Python 3.11

- #### Telegram:
    - Aiogram3

- #### Database:
    - PostgreSQL
    - Sqlalchemy

- #### Storage:
    - Redis Storage

- #### Payment:
    - CryptoPay
    - Telegram Stars
    - Telegram Payment

- #### Localization:
    - RU
    - EN

- #### Debug:
    - logger
    - pytest

## Installation 💾

[QUICK START](markdown/quick_start.md)