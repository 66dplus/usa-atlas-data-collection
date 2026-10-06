#!/usr/bin/env python3
"""Build the hand-curated research corpus. No network or production writes."""
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCESSED = "2026-10-03"
stories = []

def src(url, title, publisher, role, date, evidence, access="read_via_browser"):
    return dict(url=url, title=title, publisher=publisher, role=role,
                published_date=date, accessed_at=ACCESSED, evidence_ru=evidence,
                access_note=access)

def place(name, state, kind="city", geoid=None):
    d = dict(name=name, kind=kind, state_code=state)
    if geoid:
        d["geoid"] = geoid
    return d

def add(id, headline, summary, themes, states, places, event_date, sources,
        caveats, comparison=None, value=None, unit=None, **extra):
    d = dict(id=id, headline_ru=headline, summary_ru=summary, themes=themes,
             states=states, places=places, comparisons=[],
             period=dict(event_date=event_date, kind="dated_event"),
             verification_status="verified", sources=sources, caveats=caveats,
             refresh=dict(method="manual_source_review_then_primary_corroboration; automation_requires_publisher_permission",
                          frequency="quarterly_and_before_publication",
                          source_urls=[s["url"] for s in sources]))
    if comparison:
        d["comparisons"].append(dict(from_=places[0], to=places[1],
                                    reason_ru=comparison,
                                    comparison_type=extra.pop("comparison_type", "geographic_context")))
        d["comparisons"][0]["from"] = d["comparisons"][0].pop("from_")
    if value is not None:
        d.update(value=value, unit=unit)
    d.update(extra)
    stories.append(d)
    # Each addition is a recoverable checkpoint.
    (HERE / "stories.json").write_text(json.dumps(dict(schema_version="1.0",
        researched_at=ACCESSED, scope="wealth-industry", production_ready=False,
        verification_definition_ru="Подтверждено указанное датированное событие; текущий статус отдельно описан в caveats и period.",
        stories=stories), ensure_ascii=False, indent=2) + "\n")

add("bezos-seattle-miami-2023", "Безос объявил о переезде из Сиэтла в Майами",
    "2 ноября 2023 года Джефф Безос сообщил о личном переезде из штата Вашингтон во Флориду. В своём заявлении он назвал близость родителей и растущую роль операций Blue Origin на мысе Канаверал.",
    ["wealth", "billionaires", "personal_moves"], ["WA", "FL"],
    [place("Seattle", "WA"), place("Miami", "FL"), place("Cape Canaveral", "FL")], "2023-11-02",
    [src("https://apnews.com/article/0f04558aa909f1f5b56735e82a0a2011", "Jeff Bezos, after founding Amazon in a Seattle garage three decades ago, packs his bags for Miami", "Associated Press", "media", "2023-11-03", "AP передаёт объявление о личном переезде и названные Безосом причины."),
     src("https://www.axios.com/2023/11/03/jeff-bezos-moves-miami-blue-origin", "Jeff Bezos is moving to Miami after three decades in Seattle", "Axios", "media", "2023-11-03", "Ссылка на первоначальное заявление в Instagram.")],
    ["Дата объявления, а не установленная дата налогового резидентства.", "Исходный пост Instagram недоступен инструменту; подтверждение через AP и ссылку Axios.", "Налоговую экономию нельзя объявлять причиной по этому заявлению.", "Личный переезд не означает переезда штаб-квартиры Amazon."],
    "Контекст для сравнения Вашингтона и Флориды по миграции и концентрации богатства; один переезд не измеряет поток населения.", comparison_type="personal_move", entity_kind="person", entity_name="Jeff Bezos")

add("musk-california-texas-2020", "Маск сообщил о личном переезде в Техас раньше переезда Tesla",
    "8 декабря 2020 года Илон Маск сообщил на конференции WSJ, что переехал из Калифорнии в Техас. Отдельное объявление о корпоративной штаб-квартире Tesla последовало в 2021 году.",
    ["wealth", "billionaires", "personal_moves"], ["CA", "TX"],
    [place("California", "CA", "state", "06"), place("Texas", "TX", "state", "48")], "2020-12-08",
    [src("https://www.axios.com/2020/12/08/elon-musk-texas-california-silicon-valley", "Tesla CEO Elon Musk moves to Texas from California", "Axios", "media", "2020-12-08", "Маск публично сообщил о состоявшемся личном переезде на WSJ CEO Council."),
     src("https://www.houstonchronicle.com/news/houston-texas/space/article/Elon-Musk-confirms-that-he-has-moved-to-Texas-15784985.php", "Elon Musk confirms that he has moved to Texas", "Houston Chronicle", "media", "2020-12-08", "Сообщение интервью связывает использование времени в Техасе с проектами Tesla и SpaceX.")],
    ["Собственное заявление о проживании; налоговое резидентство административно не проверено.", "Город проживания из этих источников не устанавливается.", "Оценка состояния и статус триллионера этим событием не подтверждаются."],
    "История личной миграции между штатами; сравнение доходов не доказывает причину переезда.", comparison_type="personal_move", entity_kind="person", entity_name="Elon Musk")

add("citadel-chicago-miami-2022", "Citadel перенесла глобальную штаб-квартиру из Чикаго в Майами",
    "В июне 2022 года Citadel и Citadel Securities объявили о переезде штаб-квартир из Иллинойса во Флориду. Актуальная страница Citadel указывает глобальную штаб-квартиру в Майами; офис в Чикаго сохраняется.",
    ["wealth", "finance", "corporate_moves"], ["IL", "FL"],
    [place("Chicago", "IL"), place("Miami", "FL")], "2022-06-23",
    [src("https://www.citadelsecurities.com/news-and-insights/citadel-to-relocate-hq-from-chicago-to-miami/", "Citadel and Citadel Securities to Relocate HQ from Chicago to Miami", "Citadel Securities", "primary", "2022-06-23", "Компания официально объявила о переносе глобальных штаб-квартир."),
     src("https://www.citadel.com/who-we-are/", "Who We Are", "Citadel", "primary", None, "Текущий сайт указывает Global Headquarters, 830 Brickell Plaza, Miami, и отдельный офис Chicago."),
     src("https://www.axios.com/local/chicago/2022/06/28/corporate-headquarters-leaving-chicago", "Corporate headquarters leaving Chicago", "Axios", "media", "2022-06-28", "Переезд объявлен; офис Чикаго должен сохраняться.")],
    ["Местонахождение компании и личное проживание Кена Гриффина — разные утверждения.", "Переезд штаб-квартиры не равен переезду всех работников или закрытию офиса в Иллинойсе."],
    "Сравнение финансовых центров Чикаго и Майами; на уровне штатов — Иллинойс и Флорида.", comparison_type="corporate_headquarters_move", entity_kind="company", entity_name="Citadel / Citadel Securities")

add("tesla-corporate-hq-2021", "Tesla перенесла корпоративную штаб-квартиру в Техас",
    "7 октября 2021 года Tesla объявила о переносе корпоративной штаб-квартиры из Пало-Альто в район Остина. В последующем документе компании подтверждён переезд в 2021 году.",
    ["corporate_moves", "technology", "manufacturing"], ["CA", "TX"],
    [place("Palo Alto", "CA"), place("Austin area / Gigafactory Texas", "TX", "metro_context")], "2021-10-07",
    [src("https://www.investing.com/news/stock-market-news/austin-cheers-teslas-headquarters-move-but-local-home-buyers-left-on-edge-2640008", "Austin cheers Tesla's headquarters move, but local home buyers left on edge", "Reuters via Investing.com", "media", "2021-10-08", "Reuters сообщает объявление Маска от 7 октября: Palo Alto → Austin."),
     src("https://ir.tesla.com/_flysystem/s3/sec/000110465924048040/tm2326076d13_pre14a-gen.pdf", "Tesla 2024 preliminary proxy statement", "Tesla", "primary", "2024-04-17", "Документ компании подтверждает перенос корпоративной штаб-квартиры из Калифорнии в Остин в 2021 году.")],
    ["Октябрь — дата объявления; не дата прекращения всех операций в Калифорнии.", "Адрес Gigafactory Texas находится в Travis County; название Austin не используется как доказательство городской границы.", "Инженерная штаб-квартира рассматривается отдельной историей."],
    "Корпоративная география между Калифорнией и Техасом, с явным контекстом района Остина.", comparison_type="corporate_headquarters_move", entity_kind="company", entity_name="Tesla")

add("tesla-engineering-palo-alto-2023", "Инженерная штаб-квартира Tesla открылась в Калифорнии",
    "22 февраля 2023 года Tesla и губернатор Калифорнии представили глобальную инженерную и AI-штаб-квартиру в Пало-Альто. Корпоративная штаб-квартира компании к этому времени находилась в Техасе.",
    ["corporate_moves", "technology", "ai"], ["CA", "TX"],
    [place("Texas", "TX", "state", "48"), place("Palo Alto", "CA")], "2023-02-22",
    [src("https://www.gov.ca.gov/2023/02/22/governor-newsom-welcomes-new-tesla-global-engineering-and-ai-hq-in-california/", "Governor Newsom Welcomes New Tesla Global Engineering and AI HQ in California", "Governor of California", "primary", "2023-02-22", "Губернатор участвовал в открытии инженерной и AI-штаб-квартиры Tesla в Palo Alto."),
     src("https://www.investing.com/news/stock-market-news/tesla-set-to-make-announcement-at-california-engineering-headquarters-3010958", "Eureka! Tesla says California is still home - for its engineering HQ", "Reuters via Investing.com", "media", "2023-02-22", "Reuters различает инженерную штаб-квартиру в Калифорнии и корпоративную в Техасе.")],
    ["Это функциональное разделение штаб-квартир; обратный перенос корпоративной штаб-квартиры не заявлен.", "Сравнение state → city содержит разные географические уровни, явно указанные в kind."],
    "Иллюстрирует разные функции компании в разных штатах; не является маршрутом переезда из Техаса.", entity_kind="company", entity_name="Tesla", implementation_status="opened")

add("chevron-san-ramon-houston-2024", "Chevron объявила о переносе штаб-квартиры в Хьюстон",
    "2 августа 2024 года Chevron объявила о переносе штаб-квартиры из Сан-Рамона в Хьюстон. Компания описала постепенный перевод корпоративных функций в течение пяти лет и сохранение позиций, обслуживающих операции в Калифорнии.",
    ["corporate_moves", "energy", "employment"], ["CA", "TX"],
    [place("San Ramon", "CA"), place("Houston", "TX")], "2024-08-02",
    [src("https://chevroncorp.gcs-web.com/news-releases/news-release-details/chevron-announces-headquarters-relocation-and-senior-leadership", "Chevron Announces Headquarters Relocation and Senior Leadership Changes", "Chevron", "primary", "2024-08-02", "Официальный релиз: HQ San Ramon → Houston; корпоративные функции переходят за пять лет."),
     src("https://www.texastribune.org/2024/08/02/chevron-houston-texas-california/", "Chevron to move its headquarters from California to Texas", "The Texas Tribune", "media", "2024-08-02", "Независимое сообщение о переносе штаб-квартиры и продолжающемся присутствии в Калифорнии.")],
    ["Историческое объявление; завершение всех этапов до 2029 года здесь не проверено.", "Нельзя считать всех 2 000 работников Сан-Рамона переехавшими.", "Сохранение операций в Калифорнии прямо предусмотрено релизом."],
    "Переезд управленческого центра энергетической компании между CA и TX.", comparison_type="corporate_headquarters_move", entity_kind="company", entity_name="Chevron", implementation_status="announced_phased_transition")

add("caterpillar-deerfield-irving-2022", "Caterpillar выбрала Ирвинг для глобальной штаб-квартиры",
    "14 июня 2022 года Caterpillar объявила о переносе глобальной штаб-квартиры из Дирфилда, Иллинойс, в существующий офис компании в Ирвинге, Техас. Начало перехода было запланировано на 2022 год.",
    ["corporate_moves", "manufacturing"], ["IL", "TX"],
    [place("Deerfield", "IL", "municipality"), place("Irving", "TX")], "2022-06-14",
    [src("https://investors.caterpillar.com/news/news-details/2022/Caterpillar-to-Relocate-Global-Headquarters-to-Dallas-Fort-Worth-Area/default.aspx", "Caterpillar to Relocate Global Headquarters to Dallas-Fort Worth Area", "Caterpillar", "primary", "2022-06-14", "Компания объявила перенос глобальной штаб-квартиры из Deerfield в Irving с началом в 2022 году."),
     src("https://www.investing.com/news/stock-market-news/caterpillar-to-move-global-headquarters-to-texas-2836944", "Caterpillar to move global headquarters from Illinois to Texas", "Reuters via Investing.com", "media", "2022-06-14", "Reuters подтверждает исходный и целевой города объявления.")],
    ["Дирфилд — отдельный муниципалитет; не подменять исходный город Чикаго.", "Переезд штаб-квартиры не измеряет количество перемещённых заводов или рабочих мест."],
    "Сравнение управленческих центров производства IL и TX.", comparison_type="corporate_headquarters_move", entity_kind="company", entity_name="Caterpillar", implementation_status="historical_announcement")

add("boeing-chicago-arlington-2022", "Boeing объявила глобальную штаб-квартиру в Вирджинии",
    "5 мая 2022 года Boeing объявила, что её кампус в Арлингтоне станет глобальной штаб-квартирой вместо Чикаго. Компания назвала близость клиентов, заинтересованных сторон и технических кадров.",
    ["corporate_moves", "aerospace", "employment"], ["IL", "VA"],
    [place("Chicago", "IL"), place("Arlington County", "VA", "county", "51013")], "2022-05-05",
    [src("https://investors.boeing.com/investors/news/press-release-details/2022/Boeing-Names-Northern-Virginia-Office-Its-Global-Headquarters-Establishes-Research--Technology-Hub/default.aspx/1000/", "Boeing Names Northern Virginia Office Its Global Headquarters; Establishes Research & Technology Hub", "Boeing", "primary", "2022-05-05", "Boeing объявила глобальную штаб-квартиру на кампусе Arlington, Virginia."),
     src("https://www.axios.com/2022/05/06/boeing-relocates-virginia", "Boeing relocating headquarters to D.C.-area", "Axios", "media", "2022-05-06", "Сообщение о маршруте штаб-квартиры Chicago → Arlington, Virginia.")],
    ["Арлингтон — округ в Вирджинии, не Washington, DC.", "Наличие штаб-квартиры не означает, что всё производство Boeing находится в Вирджинии."],
    "Сравнение корпоративного присутствия Иллинойса и Вирджинии; географический уровень city → county явный.", comparison_type="corporate_headquarters_move", entity_kind="company", entity_name="Boeing")

add("hpe-san-jose-spring-2022", "HPE открыла новую штаб-квартиру в Spring, Техас",
    "О переезде из Сан-Хосе компания HPE сообщила в декабре 2020 года. 4 апреля 2022 года она объявила торжественное открытие нового кампуса штаб-квартиры в Spring, рядом с Хьюстоном.",
    ["corporate_moves", "technology"], ["CA", "TX"],
    [place("San Jose", "CA"), place("Spring", "TX", "locality")], "2022-04-04",
    [src("https://www.hpe.com/us/en/newsroom/blog-post/2022/04/hpe-celebrates-grand-opening-of-houston-headquarters.html", "HPE celebrates grand opening of Houston headquarters", "HPE", "primary", "2022-04-04", "Президент HPE описывает открытие нового кампуса в Spring, Texas, рядом с Houston."),
     src("https://www.axios.com/2020/12/02/hp-silicon-valley-texas", "HP Enterprise is leaving Silicon Valley for Texas", "Axios", "media", "2020-12-02", "Предшествующее объявление о переносе штаб-квартиры из San Jose, California."),
     src("https://www.hpe.com/us/en/about/enterprise-technology-us.html", "Enterprise Technology in the United States", "HPE", "primary", None, "Текущая страница указывает головной офис на 1701 E Mossy Oaks Rd, Spring, TX.")],
    ["Spring — локальность, не город Houston; точные муниципальные границы адреса здесь не определяются.", "HPE и HP Inc. — разные компании; история относится к Hewlett Packard Enterprise."],
    "Переход корпоративного центра CA → TX с сохранением точного названия локальности.", comparison_type="corporate_headquarters_move", entity_kind="company", entity_name="Hewlett Packard Enterprise", implementation_status="campus_opened")

add("oracle-redwood-austin-2020", "Oracle перенесла штаб-квартиру из Калифорнии в Остин",
    "В декабре 2020 года Oracle объявила о переносе штаб-квартиры из Редвуд-Сити в Остин. На проверенной 3 октября 2026 года странице офисов компания по-прежнему обозначает адрес в Остине как World Headquarters.",
    ["corporate_moves", "technology"], ["CA", "TX"],
    [place("Redwood City", "CA"), place("Austin", "TX")], "2020-12-11",
    [src("https://www.investing.com/news/stock-market-news/oracle-moves-headquarters-to-texas-from-silicon-valley-2367237", "Oracle moves headquarters to Texas from Silicon Valley", "Reuters via Investing.com", "media", "2020-12-11", "Reuters сообщает перенос корпоративной штаб-квартиры Redwood City → Austin."),
     src("https://www.oracle.com/corporate/contact/field-offices/", "United States Field Offices", "Oracle", "primary", None, "Страница указывает World Headquarters: 2300 Oracle Way, Austin, TX 78741.")],
    ["Текущая страница адресов — свидетельство на дату доступа, а не гарантия постоянного статуса.", "Личное место проживания Ларри Эллисона не выводится из местонахождения Oracle.", "Будущий кампус Nashville описан отдельно."],
    "История бизнес-географии CA → TX; не личный переезд основателя.", comparison_type="corporate_headquarters_move", entity_kind="company", entity_name="Oracle")

add("oracle-nashville-plan-2024", "Oracle назвала Nashville будущим местом мировой штаб-квартиры",
    "23 апреля 2024 года председатель Oracle Ларри Эллисон заявил, что планируемый кампус в Нэшвилле станет мировой штаб-квартирой. Он связал выбор с концентрацией медицинского бизнеса; официальный список офисов пока указывает штаб-квартиру в Остине.",
    ["corporate_moves", "technology", "healthcare", "planned_projects"], ["TX", "TN"],
    [place("Austin", "TX"), place("Nashville", "TN")], "2024-04-23",
    [src("https://apnews.com/article/cf74172176f6c90210e8ac96e1ff6f52", "Oracle's Larry Ellison says planned Nashville campus will be company's 'world headquarters'", "Associated Press", "media", "2024-04-24", "AP описывает заявление Эллисона о будущем кампусе и связи с медицинской отраслью."),
     src("https://www.oracle.com/corporate/contact/field-offices/", "United States Field Offices", "Oracle", "primary", None, "На дату доступа World Headquarters всё ещё обозначен адресом Austin, TX.")],
    ["Подтверждено объявление о намерении; завершённый перенос в TN не подтверждён.", "Председатель Эллисон в этом источнике не обозначается генеральным директором.", "Город Nashville и штат TN имеют разные уровни географии."],
    "Будущий маршрут корпоративной штаб-квартиры TX → TN; пригоден для контекста медицинских кластеров.", comparison_type="planned_corporate_headquarters_move", entity_kind="company", entity_name="Oracle", implementation_status="planned_not_confirmed_complete")

add("meta-richland-announcement-2024", "Первоначальный проект Meta в Луизиане оценивался более чем в $10 млрд",
    "4 декабря 2024 года Meta объявила о будущем дата-центре в Richland Parish с инвестициями более $10 млрд после завершения. Это историческая первая оценка кампуса; в июле 2026 года план был существенно расширен.",
    ["datacenters", "ai", "investment", "planned_projects"], ["LA"],
    [place("Louisiana", "LA", "state", "22"), place("Richland Parish", "LA", "county_equivalent", "22083")], "2024-12-04",
    [src("https://datacenters.atmeta.com/2024/12/hello-louisiana/", "Hello, Louisiana!", "Meta", "primary", "2024-12-04", "Первая оценка кампуса: более $10 млрд после завершения, более 500 операционных рабочих мест."),
     src("https://apnews.com/article/1cf320ad4d50bff8d3fac4d0535a0004", "Meta is building a massive $10 billion AI data center in Louisiana", "Associated Press", "media", "2024-12-04", "AP освещает первоначальный проект в сельском Richland Parish.")],
    ["Порог первоначального объявленного плана, не фактически потраченные деньги.", "Устаревшую оценку не показывать как актуальный бюджет 2026 года.", "Кампус не равен одному зданию и не увеличивает текущий operating-count автоматически."],
    "Связь statewide-контекста Луизианы с конкретным parish; это не сравнение двух одинаковых территорий.", value=10000000000, unit="USD_announced_investment_lower_bound", value_operator=">", entity_name="Meta Richland Parish / Hyperion", superseded_by="meta-hyperion-expansion-2026", implementation_status="historical_announcement")

add("meta-hyperion-expansion-2026", "Meta расширила план Hyperion до 5 GW и более $50 млрд",
    "13 июля 2026 года Meta сообщила о расширении кампуса Hyperion в Richland Parish до 5 GW вычислительной мощности и более $50 млрд инвестиций в регионе. Полная мощность и число будущих рабочих мест относятся к плану, а не к уже работающему объекту.",
    ["datacenters", "ai", "investment", "energy", "planned_projects"], ["LA"],
    [place("Louisiana", "LA", "state", "22"), place("Richland Parish", "LA", "county_equivalent", "22083")], "2026-07-13",
    [src("https://about.fb.com/news/2026/07/teachers-local-businesses-win-as-meta-expands-louisiana-data-center/", "Teachers and Local Businesses Win as Meta Expands Louisiana Data Center", "Meta", "primary", "2026-07-13", "Meta объявляет 5 GW и более $50 млрд; более 1 000 будущих операционных ролей и >$1,6 млрд местных контрактов."),
     src("https://siliconangle.com/2026/07/13/meta-boosts-investment-hyperion-data-center-campus-50b/", "Meta boosts investment in Hyperion data center campus to $50B+", "SiliconANGLE", "media", "2026-07-13", "СМИ подтверждает расширение и отличает новый масштаб от первоначального плана 2024 года.")],
    ["Предполагаемый масштаб полного развёртывания; не текущая измеренная электрическая нагрузка.", "Определение compute capacity используется по формулировке оператора; не подменять чистой IT-мощностью.", "Суммы 2024, 2025 и 2026 относятся к одному развивающемуся проекту; их нельзя складывать.", "На первичной странице видны обе даты July 13 и July 12; дата объявления подтверждается СМИ как 13 июля."],
    "County-level история внутри LA для сопоставления инвестиций, энергии и занятости.", value=50000000000, unit="USD_announced_regional_investment_lower_bound", value_operator=">", related_values=[dict(value=5, unit="GW_planned_compute_capacity")], entity_name="Meta Hyperion", supersedes="meta-richland-announcement-2024", implementation_status="expansion_announced_not_full_operation")

add("aws-indiana-new-carlisle-2024", "AWS объявила $11 млрд для кампуса в округе St. Joseph",
    "25 апреля 2024 года AWS объявила инвестиционный план на $11 млрд для дата-центров в St. Joseph County, Индиана, рядом с New Carlisle. Заявлено создание не менее 1 000 новых рабочих мест; строительство описано как многолетний проект.",
    ["datacenters", "ai", "investment", "employment"], ["IN"],
    [place("Indiana", "IN", "state", "18"), place("St. Joseph County", "IN", "county", "18141"), place("New Carlisle", "IN", "municipality")], "2024-04-25",
    [src("https://www.aboutamazon.com/news/aws/aws-indiana-investment-11-billion", "AWS plans to invest $11 billion in Indiana", "Amazon", "primary", "2024-04-25", "AWS объявляет $11 млрд и минимум 1 000 рабочих мест в St. Joseph County; местный чиновник описывает строительство за десятилетие."),
     src("https://apnews.com/article/ccdad82728a72025f37383e3811f13f6", "Amazon cloud computing unit plans to invest $11 billion to build data center in northern Indiana", "Associated Press", "media", "2024-04-25", "AP сообщает план near New Carlisle и называет St. Joseph County.")],
    ["Объявленный общий инвестиционный план, не кассовые расходы к 2026 году.", "Кампус и здания внутри кампуса требуют отдельного подсчёта.", "Новый план $15 млрд в 2025 году явно дополнительный; не считать его заменой $11 млрд."],
    "State → county контекст инвестиционного проекта Индианы.", value=11000000000, unit="USD_announced_investment", related_values=[dict(value=1000, unit="planned_jobs_lower_bound", operator=">=")], entity_name="AWS St. Joseph County", implementation_status="dated_investment_plan")

add("aws-mississippi-madison-2024", "В Mississippi AWS запланировала два комплекса на $10 млрд",
    "25 января 2024 года власти Mississippi одобрили стимулы для плана AWS на $10 млрд. Компания указала два индустриальных парка в Madison County и создание не менее 1 000 новых рабочих мест.",
    ["datacenters", "ai", "investment", "employment"], ["MS"],
    [place("Mississippi", "MS", "state", "28"), place("Madison County", "MS", "county", "28089")], "2024-01-25",
    [src("https://www.aboutamazon.com/news/aws/aws-10-billion-investment-mississippi", "AWS plans to invest $10 billion in Mississippi", "Amazon", "primary", "2024-01-25", "План $10 млрд для комплексов в двух промышленных парках Madison County и минимум 1 000 рабочих мест."),
     src("https://apnews.com/article/a143ba6970a4e1ff401f5463f2cd80a8", "Mississippi legislators approve incentives for 2 large data centers by Amazon Web Services", "Associated Press", "media", "2024-01-25", "AP подтверждает решение о стимулах и два проекта в Madison County.")],
    ["Два комплекса/сайта не равны двум зданиям или двум operating facilities.", "Исторический план 2024 года; последующие $3 млрд и новые объявления в штате нужно дедуплицировать отдельно.", "Одобрение стимулов не доказывает завершённый ввод."],
    "State → county контекст Mississippi, с отдельной географией будущих комплексов.", value=10000000000, unit="USD_announced_investment", related_values=[dict(value=2, unit="planned_site_complexes")], entity_name="AWS Madison County", implementation_status="historical_investment_announcement")

add("microsoft-mount-pleasant-2024", "Microsoft объявила $3,3 млрд на AI-инфраструктуру в Wisconsin",
    "8 мая 2024 года Microsoft объявила $3,3 млрд инвестиций в облачную и AI-инфраструктуру, включая кампус дата-центра в Mount Pleasant. Первичный релиз задаёт срок программы до конца 2026 года и отдельно описывает строительство и обучение работников.",
    ["datacenters", "ai", "investment", "employment"], ["WI"],
    [place("Wisconsin", "WI", "state", "55"), place("Mount Pleasant", "WI", "municipality"), place("Racine County", "WI", "county", "55101")], "2024-05-08",
    [src("https://news.microsoft.com/source/2024/05/08/microsoft-announces-3-3-billion-investment-in-wisconsin-to-spur-artificial-intelligence-innovation-and-economic-growth/", "Microsoft announces $3.3 billion investment in Wisconsin", "Microsoft", "primary", "2024-05-08", "Релиз задаёт $3,3 млрд до конца 2026 года на кампус Mount Pleasant; 2 300 строительных рабочих мест ожидаются к 2025 году."),
     src("https://apnews.com/article/ec3501d041d7b8b563563b22fcc23db5", "Biden lauds new Microsoft center on the same site where Trump's Foxconn project failed", "Associated Press", "media", "2024-05-08", "AP освещает объявление и связь локации с прежним проектом Foxconn.")],
    ["Обещанный бюджет программы — не подтверждённые текущие расходы.", "AP передаёт политическое заявление о 2 000 постоянных работниках; первичный релиз такого числа не закрепляет, поэтому число не принято.", "Место президентского выступления Sturtevant не подменяет местоположение кампуса Mount Pleasant.", "Текущий статус частичного ввода требует отдельного обновления."],
    "География кампуса внутри WI для сравнения занятости и инвестиций.", value=3300000000, unit="USD_announced_cloud_AI_investment", entity_name="Microsoft Mount Pleasant", implementation_status="dated_program_2024_through_2026")

add("google-iowa-expansion-2025", "Google объявила ещё $7 млрд для двух локаций в Iowa",
    "30 мая 2025 года Google объявила дополнительный инвестиционный план на $7 млрд в Iowa на следующие два года. Он включает новый дата-центр в Cedar Rapids, расширение Council Bluffs и развитие кадров.",
    ["datacenters", "ai", "investment", "workforce"], ["IA"],
    [place("Cedar Rapids", "IA"), place("Council Bluffs", "IA")], "2025-05-30",
    [src("https://blog.google/feed/new-7-billion-investment-iowa/", "Google announces new $7 billion investment in Iowa", "Google", "primary", "2025-05-30", "Google объявляет дополнительные $7 млрд за два года: Cedar Rapids, Council Bluffs, кадровые программы."),
     src("https://www.kcrg.com/2025/05/30/google-holds-celebration-new-data-center-cedar-rapids/", "Google holds celebration for new data center in Cedar Rapids", "KCRG", "media", "2025-05-30", "Местное СМИ подтверждает объявление на строительной площадке Cedar Rapids."),
     src("https://www.kcrg.com/2026/05/27/cedar-rapids-mayor-deliver-state-city-address/", "Cedar Rapids Mayor defends data centers, pleads for civility in State of City", "KCRG", "media", "2026-05-27", "В мае 2026 года СМИ продолжает описывать строительство кампусов Google и QTS в Cedar Rapids.")],
    ["Не распределять все $7 млрд только на Cedar Rapids: план охватывает обе локации и обучение.", "Инвестиции в течение двух лет не означают уже потраченные $7 млрд.", "Заявление 2026 года о продолжающемся строительстве не устанавливает статус каждой отдельной очереди."],
    "Две локации одного statewide-плана; городские суммы по отдельности неизвестны.", comparison_type="in_state_project_locations", value=7000000000, unit="USD_announced_two_year_statewide_investment", entity_name="Google Iowa", implementation_status="investment_program_and_construction")

add("three-mile-island-microsoft-2024", "Соглашение Microsoft поддержало план перезапуска Three Mile Island Unit 1",
    "20 сентября 2024 года Constellation объявила 20-летнее соглашение о продаже энергии Microsoft и план перезапуска блока 1 Three Mile Island в Pennsylvania под названием Crane Clean Energy Center. Объявленная мощность — около 835 MW.",
    ["datacenters", "energy", "nuclear", "planned_projects"], ["PA"],
    [place("Pennsylvania", "PA", "state", "42"), place("Londonderry Township", "PA", "municipality")], "2024-09-20",
    [src("https://investors.constellationenergy.com/news-releases/news-release-details/constellation-launch-crane-clean-energy-center-restoring-jobs", "Constellation to Launch Crane Clean Energy Center", "Constellation Energy", "primary", "2024-09-20", "Объявление 20-летнего PPA с Microsoft для перезапуска Unit 1, около 835 MW."),
     src("https://apnews.com/article/8f47ba63a7aab8831a7805dfde0e2c39", "The AI boom may give Three Mile Island a new life supplying power to Microsoft's data centers", "Associated Press", "media", "2024-09-20", "AP подтверждает план перезапуска для энергоснабжения дата-центров и необходимость разрешений.")],
    ["Блок 1 — не аварийный блок 2 1979 года.", "Проект энергогенерации не является новым дата-центром и не увеличивает число дата-центров PA.", "Не утверждать, что Microsoft получает всё питание по выделенному прямому кабелю.", "Первоначальный срок 2028 года может измениться; текущий ввод здесь не подтверждён."],
    "Контекст энергоснабжения дата-центров; география генератора не устанавливает географию всех покупателей энергии.", value=835, unit="MW_planned_generation_capacity_approximate", entity_name="Crane Clean Energy Center / TMI Unit 1", implementation_status="restart_plan_power_agreement")

add("duane-arnold-google-2025", "Google и NextEra договорились о будущем перезапуске АЭС в Iowa",
    "27 октября 2025 года Google и NextEra объявили соглашение для перезапуска Duane Arnold Energy Center рядом с Cedar Rapids. Публично заявленная мощность — 615 MW; ожидаемое возобновление работы относится к 2029 году.",
    ["datacenters", "energy", "nuclear", "planned_projects"], ["IA"],
    [place("Iowa", "IA", "state", "19"), place("Palo / Duane Arnold Energy Center", "IA", "locality")], "2025-10-27",
    [src("https://www.investor.nexteraenergy.com/~/media/Files/N/NEE-IR/news-and-events/news-releases/2025/NextEra%20Energy%20and%20Google%20Announce%20New%20Collaboration%20to%20Accelerate%20Nuclear%20Energy%20Deployment%20in%20the%20US.pdf", "NextEra Energy and Google Announce New Collaboration to Accelerate Nuclear Energy Deployment in the U.S.", "NextEra Energy", "primary", "2025-10-27", "Компании объявили соглашение о перезапуске 615-MW Duane Arnold; доступность мощности — после возобновления работы."),
     src("https://www.marketscreener.com/news/nextera-energy-partners-with-google-to-restart-iowa-nuclear-plant-ce7d5ddfdc88ff23", "NextEra Energy partners with Google to restart Iowa nuclear plant", "Reuters via MarketScreener", "media", "2025-10-27", "Reuters указывает ожидаемый перезапуск в начале 2029 года.")],
    ["615 MW — проектная мощность генерации, не число или действующая нагрузка дата-центров.", "Перезапуск зависит от разрешений и работ; не показывать как уже работающий источник.", "Рядом с Cedar Rapids не означает внутри административной границы города."],
    "State → locality контекст связи AI-инфраструктуры с энергетическими проектами Iowa.", value=615, unit="MW_planned_generation_capacity", entity_name="Duane Arnold Energy Center", implementation_status="restart_planned_2029")

add("northern-virginia-global-capacity-2024", "Аудит Virginia оценил роль северной части штата в мировой мощности дата-центров",
    "В отчёте JLARC декабря 2024 года Northern Virginia названа крупнейшим рынком дата-центров: около 13% сообщённой операционной мощности в мире и 25% в Америке. Эти доли относятся к мощности рынка, а не к числу зданий.",
    ["datacenters", "regional_concentration", "energy"], ["VA"],
    [place("Virginia", "VA", "state", "51"), place("Northern Virginia", "VA", "region")], "2024-12-09",
    [src("https://jlarc.virginia.gov/landing-2024-data-centers-in-virginia.asp", "Data Centers in Virginia", "Virginia JLARC", "primary", "2024-12-09", "Государственный аудит указывает 13% глобальной и 25% американской сообщённой операционной мощности Northern Virginia."),
     src("https://www.publicpower.org/periodical/article/report-details-challenges-virginia-power-grid-tied-growth-data-centers", "Report Details Challenges to Virginia Power Grid Tied to Growth of Data Centers", "American Public Power Association", "media", "2024-12-13", "Отраслевое издание пересказывает доли из JLARC и энергетические последствия.")],
    ["Reported operational capacity — база опубликованных сведений, не перепись всех дата-центров мира.", "Northern Virginia — регион, не весь штат и не только Loudoun County.", "Доли исторического отчёта не подтверждены как текущий мировой рейтинг октября 2026 года.", "Источник издания отраслевой ассоциации обозначен media; его пересказ не независим от JLARC."],
    "State → region контекст концентрации мощностей; сравнение со всем миром не поддерживается как обычная пара штатов.", value=13, unit="percent_reported_global_operational_capacity", related_values=[dict(value=25, unit="percent_reported_Americas_operational_capacity")], entity_name="Northern Virginia data-center market", implementation_status="historical_report_estimate")

add("aws-indiana-additional-investment-2025", "AWS объявила дополнительные $15 млрд для северной Indiana",
    "24 ноября 2025 года Amazon объявила дополнительные $15 млрд для новых кампусов в северной Indiana. Компания прямо отделяет этот план от $11 млрд, объявленных в St. Joseph County годом ранее, и указывает будущую мощность 2,4 GW.",
    ["datacenters", "ai", "investment", "energy", "planned_projects"], ["IN"],
    [place("Indiana", "IN", "state", "18"), place("Northern Indiana", "IN", "region")], "2025-11-24",
    [src("https://www.aboutamazon.com/news/company-news/amazon-15-billion-indiana-data-centers", "Amazon plans to invest $15 billion in Northern Indiana to build new data center campuses and advance AI innovation", "Amazon", "primary", "2025-11-24", "План $15 млрд назван дополнительным к St. Joseph County; новые площадки по Indiana и будущие 2,4 GW."),
     src("https://www.investing.com/news/stock-market-news/amazon-to-invest-15-billion-in-indiana-to-boost-data-center-infrastructure-4375851", "Amazon to invest $15 billion in Indiana to boost data center infrastructure", "Reuters via Investing.com", "media", "2025-11-24", "Reuters подтверждает объявление о $15 млрд в Northern Indiana для AI/cloud кампусов.")],
    ["Новые кампусы не привязаны целиком к St. Joseph County; county остаётся неизвестным без уточнения площадок.", "Дополнительный план и прежние $11 млрд не означают уже потраченные $26 млрд.", "2,4 GW — заявленный будущий масштаб проекта, не текущая измеренная нагрузка."],
    "State → region география нового плана; county нельзя унаследовать от объявления 2024 года.", value=15000000000, unit="USD_additional_announced_investment", related_values=[dict(value=2.4, unit="GW_planned_data_center_capacity")], entity_name="AWS Northern Indiana expansion", implementation_status="additional_investment_plan")

# All claims above were manually researched. Build compact review outputs from them.
with (HERE / "stories.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id", "headline_ru", "states", "themes", "event_date", "verification_status", "implementation_status", "value", "unit", "source_urls"])
    w.writeheader()
    for d in stories:
        w.writerow(dict(id=d["id"], headline_ru=d["headline_ru"], states="|".join(d["states"]),
            themes="|".join(d["themes"]), event_date=d["period"]["event_date"], verification_status=d["verification_status"],
            implementation_status=d.get("implementation_status", "dated_fact"), value=d.get("value", ""), unit=d.get("unit", ""),
            source_urls="|".join(s["url"] for s in d["sources"])))

source_map = {}
for d in stories:
    for s in d["sources"]:
        rec = source_map.setdefault(s["url"], dict(s, story_ids=[]))
        rec["story_ids"].append(d["id"])
(HERE / "source-register.json").write_text(json.dumps(dict(accessed_at=ACCESSED,
    collection_policy="URL and authored factual paraphrases only; no article mirrors, photos, ranking tables or blocked-source circumvention",
    sources=list(source_map.values())), ensure_ascii=False, indent=2) + "\n")

collections = [
    ("people-on-the-move", "Личные переезды состоятельных людей", ["personal_moves"]),
    ("headquarters-geography", "Куда перемещаются штаб-квартиры", ["corporate_moves"]),
    ("ai-investment-map", "Где строится AI-инфраструктура", ["investment"]),
    ("powering-the-cloud", "Энергия для облака", ["energy"]),
    ("concentration-and-local-impact", "Концентрация и местные последствия", ["regional_concentration", "employment"]),
]
(HERE / "collections.json").write_text(json.dumps(dict(collections=[dict(id=i, title_ru=t,
    story_ids=[d["id"] for d in stories if set(tags)&set(d["themes"])]) for i,t,tags in collections]), ensure_ascii=False, indent=2)+"\n")
summary = dict(verified_stories=len(stories), states_covered=sorted({s for d in stories for s in d["states"]}),
               source_urls=len(source_map), publishers=sorted({s["publisher"] for s in source_map.values()}),
               missing_51_state_coverage=True, production_ready=False)
(HERE / "coverage.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
print(json.dumps(summary, ensure_ascii=False))
