# Примери: въпрос → период + филтри + извиквания

„Днес“ в примерите е четвъртък, 01.10.2026 г. (Europe/Sofia). Скриптовете се пускат от
папката на скила; всяка стъпка е **едно** извикване, без `|`, `>` и `&&`.

## Как се превръща въпросът в период

| Израз | Период |
|---|---|
| днес / вчера | 2026-10-01 / 2026-09-30 |
| снощи / тази нощ / вчера вечерта | вчера и днес: 2026-09-30 – 2026-10-01 (нощта минава през полунощ) |
| тази седмица | от понеделник до днес: 2026-09-28 – 2026-10-01 |
| миналата седмица | понеделник – неделя: 2026-09-21 – 2026-09-27 |
| последните 7 дни | 2026-09-25 – 2026-10-01 (днес включително) |
| този месец | 2026-10-01 – 2026-10-01 |
| миналия месец | 2026-09-01 – 2026-09-30 |
| „през август“ без година | последният август, който вече е започнал: 2026-08-01 – 2026-08-31 |
| тази година / „за годината“ | 2026-01-01 – 2026-10-01 |
| миналата година / „през 2025“ | 2025-01-01 – 2025-12-31 |
| лятото | 2026-06-01 – 2026-08-31 |
| пожарният сезон | ако потребителят не уточни – питай; не измисляй граници |

Казвай периода в отговора с дати: „за 01.08.2026 – 31.08.2026 г.“.

**Над 366 дни** → по едно извикване за всяка календарна година (последното – до днес),
всеки път в отделен файл; `incident_stats.py` приема всички файлове наведнъж и не брои
двойно.

## Търсене

### „Покажи пожарите в МПС тази седмица“

```bash
python3 _shared/scripts/fetch_incidents.py --from 2026-09-28 --to 2026-10-01 --filter ucasulaty="транспортни средства" -o mps.json
```

Без `--all` – пожарите в МПС са с преки материални загуби. Ако резултатът е 0, опитай още
веднъж с `--all` и същия филтър (пожар без загуби в МПС е рядкост, но се среща) и кажи
кой вариант е показан. Таблица (дата, населено място, обект, причина, служба, статус) –
от записите в `mps.json`.

### „Кои пожари в района на РСПБЗН – Кнежа не са приключени?“

„Не са приключени“ = причината е „в процес на установяване“. Периодът не е казан → тази
година, и го кажи.

```bash
python3 _shared/scripts/fetch_incidents.py --from 2026-01-01 --to 2026-10-01 --filter unit=Кнежа --filter reason="в процес на установяване" -o knezha.json
```

Ако потребителят има предвид незавършени записи („само сигналът“) – `--all --filter
status=open`. При съмнение покажи първото и кажи с едно изречение за второто.

### „Пожарите в с. Бохот през 2025“

```bash
python3 _shared/scripts/fetch_incidents.py --from 2025-01-01 --to 2025-12-31 --all --filter casulaty="пожар с" --filter casulaty="пожар без" --place Бохот -o bohot.json
```

`--place`, не `--filter location=Бохот` – иначе се изпускат пожарите, отчетени към друго
населено място, но с Бохот в адреса („пътя Плевен – Бохот“, землището). Търсенето е
„съдържа“ – по `matched_in` и по самите полета провери, че всеки запис е наистина за това
село (не друго с подобно име, не улица със същото име); различните кажи.

### „Ходили ли са от пожарната снощи на катастрофата в Ясен?“

Въпрос за едно произшествие: вчера и днес, всички видове, мястото с `--place`, **без**
филтър за вид.

```bash
python3 _shared/scripts/fetch_incidents.py --from 2026-09-30 --to 2026-10-01 --all --place Ясен -o yasen.json
```

Връща и катастрофата (`location` „пътя Плевен-Ясен“), и второто излизане след нея –
техническа помощ с `location` „гр. Плевен“, адрес „гр. Плевен, пътя Плевен-Ясен“ и обект
„измиване на пътното платно след ПТП“. В отговора са **и двете**, по реда на часовете, с
извършената работа от `object` и `detail.activity_area`. С `--filter location=Ясен` второто
се губи.

## Статистика

### „Колко пожара имаше в Левски през август?“

„В Левски“ е двусмислено: градът (`location`) или районът на РСПБЗН – Левски (`unit`).
Без друго уточнение – **районът на службата** (така се отчита), и го кажи; ако въпросът е
явно за града („в град Левски“) – `location`.

```bash
python3 _shared/scripts/fetch_incidents.py --from 2026-08-01 --to 2026-08-31 --all --filter casulaty="пожар с" --filter casulaty="пожар без" --filter unit=Левски --limit 5000 -o levski_08.json
python3 scripts/incident_stats.py levski_08.json --group-by kind
```

Отговор: общият брой и разбивката „с преки материални загуби / без“.

### „Сравни юли 2025 и юли 2026 по причини“

```bash
python3 _shared/scripts/fetch_incidents.py --from 2025-07-01 --to 2025-07-31 -o jul2025.json
python3 _shared/scripts/fetch_incidents.py --from 2026-07-01 --to 2026-07-31 -o jul2026.json
python3 scripts/incident_stats.py jul2025.json jul2026.json --group-by cause --compare-field year
```

Без `--all`: причина се установява само за пожарите с преки материални загуби (за
останалите е „не се изисква“). Ако потребителят иска всички пожари – добави `--all` и
двата филтъра за пожар; „не се изисква“ тогава е голямата група и го обясни.

### „Разпредели пожарите по обекти за годината“

```bash
python3 _shared/scripts/fetch_incidents.py --from 2026-01-01 --to 2026-10-01 --all --filter casulaty="пожар с" --filter casulaty="пожар без" --limit 5000 -o pozhari_2026.json
python3 scripts/incident_stats.py pozhari_2026.json --group-by object_class
```

`object_class` (класификаторът) – не `object` (свободен текст с десетки варианти).
`period.empty_months` ще покаже празните месеци – кажи ги.

### „Топ 5 населени места по брой пожари“

```bash
python3 _shared/scripts/fetch_incidents.py --from 2026-01-01 --to 2026-10-01 --all --filter casulaty="пожар с" --filter casulaty="пожар без" --limit 5000 -o pozhari_2026.json
python3 scripts/incident_stats.py pozhari_2026.json --group-by settlement --top 5
```

### „Колко пожара по служби и по причини за 2025?“ (две полета)

```bash
python3 _shared/scripts/fetch_incidents.py --from 2025-01-01 --to 2025-12-31 -o pmz_2025.json
python3 scripts/incident_stats.py pmz_2025.json --group-by service --group-by cause
```

### „Пожари с материални загуби по години от 2021 до сега“ (над 366 дни)

```bash
python3 _shared/scripts/fetch_incidents.py --from 2021-01-01 --to 2021-12-31 -o pmz_2021.json
python3 _shared/scripts/fetch_incidents.py --from 2022-01-01 --to 2022-12-31 -o pmz_2022.json
python3 _shared/scripts/fetch_incidents.py --from 2023-01-01 --to 2023-12-31 -o pmz_2023.json
python3 _shared/scripts/fetch_incidents.py --from 2024-01-01 --to 2024-12-31 -o pmz_2024.json
python3 _shared/scripts/fetch_incidents.py --from 2025-01-01 --to 2025-12-31 -o pmz_2025.json
python3 _shared/scripts/fetch_incidents.py --from 2026-01-01 --to 2026-10-01 -o pmz_2026.json
python3 scripts/incident_stats.py pmz_2021.json pmz_2022.json pmz_2023.json pmz_2024.json pmz_2025.json pmz_2026.json --count-only --compare-field year
```

### „По месеци“ / „по дни от седмицата“ / „по часове“

`--group-by month`, `--group-by weekday`, `--group-by hour`. Месеците на две години една до
друга: `--group-by month_of_year --compare-field year` (`month` съдържа годината и не
става за това). Групите идват по брой – в отговора ги подреди по календара.

### Графика към сравнение

```bash
python3 scripts/incident_stats.py jul2025.json jul2026.json --group-by cause --compare-field year -o stats.json
python3 scripts/incident_chart.py stats.json --title "Пожари с преки материални загуби по причини, юли 2025 и юли 2026 г." -o "/mnt/user-data/outputs/Grafika_Pozhari_Prichini_2025-07_2026-07.svg"
```

### „Покажи ги на карта“ (след търсене)

```bash
python3 scripts/incident_map.py pozhari_09.json --title "Пожари, септември 2026 г." -o "/mnt/user-data/outputs/Karta_Pozhari_2026-09-01_2026-09-30.svg"
```

### „Направи справка за пожара в Тръстеник на 12.09“ (от списъка)

Пожарът е с преки материални загуби и е в намерените записи → предай на `spravka-prichina`
датата 2026-09-12 и `id` на записа; тя го взима с
`python3 _shared/scripts/fetch_incidents.py 2026-09-12 --filter id=<id>`.

### Таблица за Excel

```bash
python3 scripts/incident_stats.py pozhari_2026.json --group-by service --group-by cause -o stats.json
python3 scripts/export_incidents_xlsx.py pozhari_2026.json --stats stats.json -o "/mnt/user-data/outputs/Pozhari_RDPBZN_Pleven_2026-01-01_2026-10-01.xlsx"
```
