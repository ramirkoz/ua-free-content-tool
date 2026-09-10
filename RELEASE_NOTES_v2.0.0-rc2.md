# UA FREE Content Tool v2.0.0-rc2

## Hotfix OpenRouter fallback limit

RC2 виправляє помилку першого production-тесту OpenRouter у V2 RC1.

- OpenRouter приймає масив `models` максимум із трьох елементів. RC1 помилково відправляв до чотирьох кандидатів, що давало HTTP 400: `models array must have 3 items or fewer`.
- RC2 передає максимум три моделі в одному OpenRouter-запиті.
- Внутрішня автоматична маршрутизація FAST_CHEAP / BALANCED / STRONG / PREMIUM збережена. Якщо запит не завершується успішно, зовнішній V2 router може перейти на наступний quality tier окремим запитом у межах заданого ліміту спроб.
- Жорсткий backend switch не змінено: OpenRouter не провалюється в AI Router або Agent.
- Дані та схема БД не змінюються. `Data` до ZIP не входить.

Це точковий hotfix RC1 без зміни редакційного або публікаційного pipeline.
