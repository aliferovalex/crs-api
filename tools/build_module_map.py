# -*- coding: utf-8 -*-
"""Generate the current CRS / ibcmd-rs module map."""
import argparse,ast,json,re,sys
from pathlib import Path
from xml.etree import ElementTree as E
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'/'Сериализация'))
import metadata_structure

PURPOSES = {'compiled_dependencies': 'Общие связи служебного графа из подтверждённых UUID, объявленных типов и хранимых детей; проверка изменённых ссылок корня и сохранение непрозрачных исходных связей.','compiled_graph': 'Общие факты идентичности: UUID, имя, возможности, генерируемые типы и дочерние коллекции из XML, подтверждённые нативным CF.','compiled_image': 'Полное различие нативных CF: создание, изменение и удаление тел и потоков с проверкой принадлежности объектам.','compiled_creation': 'Метаданные новых владельцев и управляемых форм из проверенного CF: UUID, возможности, потоки, позиция и связи; приложение не сериализуется повторно.','repository_baseline': 'Инициализация XML-основы и рабочей папки без обязательного Git; квитанции пакетов и атомарное продвижение основы после проверки серверного состояния.',
 'partial_baseline': 'Частичное XML-представление поверх полного неизменяемого CF: файловая карта покрытия, явные недоступные владельцы и потоки, выборочное копирование файлов по UUID. Автоматические удаления и полная компиляция запрещены.',
 'configuration_version': 'Чтение свойства Version корня из проверенного адресного снимка или итогового пакета для поля code истории помещения; без полной выгрузки и без записи в хранилище.',
 'export_snapshot': 'Общая карта версий полной XML-выгрузки и безопасная запись файлов снимка.',
'compiled_metadata': 'Контракты внешнего компилятора: реквизиты владельцев и полные управляемые формы, извлечение '
                      'итоговых UUID возможностей, согласование типов и зависимостей, проверка '
                      'привязок. Использует общие нативные читатели; не записывает нативные '
                      'свойства.',
 'configuration_commit': 'Компиляция полной выгрузки через ibcmd-rs, удаление хранимых детей, проверки версий и единый '
                         'пакет помещения.',
 'configuration_export': 'Инвентаризация файлов выгрузки и определение операций.',
 'export_xml': 'Чтение и проверка XML: export_xml.',
 'external_data': 'Чтение тел объектов и внешних потоков из пакета версии.',
 'external_dependencies': 'Проверка внешних ссылок при удалении; UUID генерируемых типов объектов и вложенных возможностей берутся из подтверждённого индекса исходного CF, без профилей классов.',
 'form_attribute_types': 'Типы всех объявлений формы: реквизиты, колонки и параметры; общий читатель типов метаданных.',
 'ibcmd_backend': 'Внешний компилятор CF ↔ XML: cf load, при отказе полная cf bootstrap --base-free; привязка служебных заголовков, замкнутая проверка всех файлов и результата, общий контроль полноты нативных активов через export_coverage.',
 'metadata_classes': 'Получение справочника классов метаданных через Python-вход.',
 'metadata_context': 'Чтение updateInfo, проверка UUID и карты отдельно хранимых детей.',
 'metadata_identifiers': 'UUID классов, коллекций, типов значений и служебных возможностей; XML-имена классов сопоставляются со служебными именами по карте схемы.',
 'metadata_references': 'Значения DesignTimeRef: перечисления, EmptyRef и предопределённые элементы; проверка владельцев и зависимостей форм.',
 'native_predefined_reader': 'Чтение имён и UUID предопределённых элементов из нативных потоков справочников и планов; схемы колонок, вложенность и проверка дубликатов, без записи свойств.',
 'metadata_structure': 'Карта классов, дочерних коллекций и их правил хранения.',
 'metadata_targets': 'Индекс текущих и итоговых объектов для разрешения ссылок.',
 'metadata_type_references': 'Ссылочные типы свойств Type: сопоставление XML-имён с UUID типов '
                             'итоговой конфигурации.',
 'metadata_type_sets': 'Проверенные групповые типы платформы: XML TypeSet, постоянные UUID и '
                       'запрет их подмены.',
 'native_commands': 'Чтение и проверка нативных данных: native_commands.',
 'native_configuration_reader': 'Чтение свойств и UUID возможностей корня; проверка хранимых дочерних коллекций по UUID классов из схемы без записи нативных свойств.',
 'export_coverage': 'Контроль полноты CF → XML по общей карте потоков: модули, составные формы, справка и вложения, картинки, макеты и непрозрачные активы; неизвестные непустые потоки блокируются.',
 'native_streams': 'Принадлежность потоков объектам и объявленным внутренним UUID; общая классификация CF: интерфейс и модуль формы, справка, права, содержимое макета, модули и непрозрачные дополнения; без преобразования содержимого.',
 'native_content': 'Общий результат преобразования: метаданные, тело, потоки и их версии; без '
                   'упаковки пакета.',
 'native_features': 'Чтение и проверка нативных данных: native_features.',
 'native_form_bindings': 'Чтение и проверка нативных данных: native_form_bindings.',
 'native_form_profiles': 'Чтение и проверка нативных данных: native_form_profiles.',
 'native_form_reader': 'Чтение и проверка нативных данных: native_form_reader.',
 'native_form_roles': 'Чтение и проверка нативных данных: native_form_roles.',
 'native_inline': 'Чтение и проверка нативных данных: native_inline.',
 'native_metadata': 'Нативное дерево, текст, двоичные записи, сжатие и контейнер хранилища.',
 'native_object_profiles': 'Чтение и проверка нативных данных: native_object_profiles.',
 'native_object_reader': 'Чтение и проверка нативных данных: native_object_reader.',
 'native_references': 'Итоговые ссылки на типы и значения: подготовленные нативные определения '
                      'либо проверенные исходные снимки/пакет версии.',
 'native_tabular': 'Чтение и проверка нативных данных: native_tabular.',
 'packet_builder': 'Граф помещения, версии, записи объектов и итоговый XML-запрос.',
 'platform_profiles': 'Выбор профиля платформы и структуры выгрузки.',
 'role_rights_native': 'Чтение нативных прав и ссылок для проверки зависимостей.',
 'schema_content': 'Чтение нативного контейнера СКД для проверки зависимостей.',
 'serialization_context': 'Сопоставление снимка с updateInfo и проверка исходной версии.',
 'serializer_cli': 'Общий JSON-вход Python, ограничения и запись результата.',
 'cf_container': 'Встроенное чтение и запись контейнеров CF Format15/Format16; адаптированный MIT-код без внешних Python-зависимостей.',
 'xml_compare': 'Общее сравнение XML/QName и содержимого файлов для плана, сборки CF и обратной сверки; проверка имён.',
 'xml_namespaces': 'Пространства имён XML и сохранение префиксов QName.',
 'xml_qnames': 'Чтение и проверка XML: xml_qnames.',
 'xml_type_text': 'Чтение и проверка XML: xml_type_text.',
 'ВерсияХранилища': 'Модель версии хранилища.',
 'Вспомогательный': 'Служебные операции протокола и кодирования.',
 'ИдентификаторыМетаданных': 'Доступ OneScript к UUID классов и коллекций.',
 'КлиентХранилища': 'Вызовы через общий HTTP/TCP-транспорт: снимки, захваты, подготовка, помещение и проверки результата.',
 'ТранспортХранилища': 'Выбор HTTP или TCP, приветствие сервера, буферизованное чтение, длины сообщений и маркеры конца; без повторной отправки при ошибке.',
 'ОтветТранспортаХранилища': 'Код состояния и XML-тело ответа TCP в общем интерфейсе клиента.',
 'МенеджерЗапросов': 'Формирование XML-запросов протокола хранилища.',
 'МенеджерХранилищ': 'Операции сервера и управление хранилищами.',
 'ОбработкаXML': 'Разбор ответов сервера, контекста и описаний объектов.',
 'ОбъектХранилища': 'Описание объекта и проверки допустимости операций.',
 'ОтветСервиса': 'Модель ответа сервера и его ошибок.',
 'ПодготовкаПомещенияКонфигурации': 'Составная подготовка: владение новыми захватами, сохранение прежних, проверка версий и reviseDate, помещение и подтверждение по квитанции без повторной отправки.',
 'ПакетПомещенияОбъекта': 'Модель пакета, его импорт и проверка состава.',
 'ПараметрыСозданияХранилища': 'Параметры создания нового хранилища.',
 'ПользовательХранилища': 'Описание пользователя хранилища.',
 'ПравилаПакетовХранилища': 'Правила операций и состава пакетов по классам объектов.',
 'РолиХранилища': 'Роли и права пользователей хранилища.',
 'СериализаторОбъектаХранилища': 'Подготовка JSON для Python и импорт подготовленных пакетов.',
 'СнимокОбъектаХранилища': 'Снимок объекта и версия хранилища, на которой он прочитан.',
 'СовместимостьПлатформы': 'Проверка поддерживаемого профиля платформы.'}

PURPOSES['preparation_journal'] = 'Журнал составной подготовки: атомарное состояние, владение процессом, блокировка записи, неизменяемый пакет и явное восстановление без повторной отправки.'

CONTRACTS = [('ТранспортХранилища','ПроверитьРазмерСообщения','Размер полного UTF-8 XML-запроса с base64 либо объявленная длина TCP-ответа','Общий предел 256 МиБ; слишком большое сообщение отклоняется до сетевой отправки'),
 ('preparation_journal','run','create/save: состояние и кэш; claim: каталог журнала, UUID пользователя, ответ depotInfo и платформа','Ревизия журнала; при восстановлении — сохранённый пакет, квитанция, метки захватов и безопасная фаза; пароль не сохраняется'),
 ('КлиентХранилища','ВосстановитьПодготовкуПомещения','Каталог завершённой подготовки и Python; подключённый пользователь того же хранилища','Восстановленная подготовка для отмены собственных захватов или подтверждения исхода; повторное помещение запрещено'),
 ('КлиентХранилища','ПодготовитьПомещениеКонфигурации','Полная XML-папка, известная основа и настройки кэша/ibcmd/Git','ПодготовкаПомещенияКонфигурации: согласованные пути, пакет и только нужные захваты; например свойство справочника → захват UUID справочника перед компиляцией'),
 ('ПодготовкаПомещенияКонфигурации','Поместить','Готовая подготовка и комментарий','Один вызов помещения, обновлённая основа и снятие собственных захватов; прежние захваты остаются'),
 ('ПодготовкаПомещенияКонфигурации','ПодтвердитьПомещение','Неизвестный исход либо не обновлённая основа и сохранённый пакет с квитанцией','Проверенное получение результата без повторного помещения'),
('native_streams','select','Метаданные объекта с полем 13 и имена потоков CF','UUID объекта и объявленных внутренних объектов; только принадлежащие им потоки, например feature_uuid.7 → модуль сеанса корня'),
('export_coverage','require_complete_export','Образ CF, записи полной XML-выгрузки, словарь путь → байты','Успех либо отказ с именем отсутствующего файла/неизвестного потока; например Form.0 → Form.xml + непустой Module.bsl'),
('configuration_export',
  'plan',
  'Полная исходная и целевая XML-папки, контекст хранилища',
  'Операции, отпечатки, UUID'),
 ('configuration_commit', 'prepare', 'Те же папки и контекст', 'План снимков и изменения'),
 ('configuration_commit',
  'serialize',
  'План, снимки, версии, storage, compiler={backend, executable, base_cf}',
  'data, descriptions, requested, externals'),
 ('ibcmd_backend',
  'Compiler.prepare',
  'Запрос, план, изменения и объекты контекста',
  'Проверенные образы before/after CF'),
 ('compiled_metadata',
  'content',
  'Изменение, контекст и образы CF',
  'ObjectContent(docs, body, streams, externals)'),
 ('packet_builder', 'assemble', 'Граф и ObjectRecord', 'Единый двоичный пакет хранилища')]

PURPOSES['repository_cache'] = 'Инкрементальный кэш CF: версии объектов и потоков, выборочное получение, удаления, контроль целостности и атомарная смена поколения.'
PURPOSES['xml_git'] = 'XML-проект Git: коммит каждой полученной версии хранилища в настраиваемой source_branch, трёхстороннее слияние и отдельные рабочие копии без изменения входных папок.'
CONTRACTS += [('repository_cache','Cache.plan','Контекст хранилища и проверенный кэш','UUID изменённых тел, нужные потоки, удаления и поколение'),
              ('repository_cache','Cache.update','План, контекст, выбранные снимки и подтверждённая версия','Путь base_cf нового поколения и статистика получения'),
              ('repository_cache','Cache.source','Свежий контекст и UUID нужных снимков','Снимки и полное хранилище исходных данных, собранные локально из кэша')]
CONTRACTS += [('repository_cache','Cache.bootstrap','Полный нативный пакет версии, контекст и неизменившийся UUID версии','Первый CF без seed_cf и проверенное поколение кэша'),
              ('repository_baseline','initialize','Проверенный кэш, ibcmd-rs и необязательная рабочая XML-папка','Неизменяемая XML-основа, рабочая папка и манифест; Git не требуется'),
              ('repository_baseline','read','Каталог кэша с baseline.json','Проверенные пути основы и CF; повреждения прекращают чтение')]
CONTRACTS += [('repository_baseline','register','Скомпилированный пакет, XML-снимок, изменённые тела и потоки','Квитанция с хешем пакета, ожидаемыми серверными записями и UUID основы'),
              ('repository_baseline','advance','Квитанция, пакет и полученное поколение кэша','Новая основа только при полном совпадении серверных данных; рабочие файлы сохраняются')]
CONTRACTS += [('compiled_dependencies','reconcile','Исходный и итоговый CF, полные объявления XML, исходные связи','Нативный список зависимостей: замена доказанных связей, сохранение непрозрачных и структурных'),
              ('compiled_graph','TypeIndex.reference','Полное имя типа cfg:…, декларации XML и нативные записи CF','UUID типа и UUID владельца либо возможности корня; подтверждение по CF'),
              ('compiled_graph','read','Элемент полной XML-выгрузки, карта объектов, нативные записи CF и платформа','Facts: подтверждённые UUID, имя, класс, родитель, возможности, генерируемые типы и хранимые дети'),
              ('compiled_creation','allocate','Новый объект XML, проверенный CF, снимок корня и полная карта объектов','ObjectContent нового объекта с версиями тела и потоков'),
              ('compiled_creation','finalize','ObjectContent и полный итоговый индекс ссылок','Проверенные UUID типов и зависимости нового объекта'),
              ('configuration_export','positions','Полное дерево метаданных XML','Позиции объектов по классам в коллекциях родителей')]
CONTRACTS += [('native_configuration_reader','stored_collections','Нативный корень CF, UUID корня и платформа','Карта UUID класса → UUID дочерних объектов; проверенные счётчики и уникальность')]
CONTRACTS += [('native_content','compiled_stream_changes','Снимок, исходные и итоговые потоки CF, имена принадлежащих объекту потоков','ObjectContent: новые версии изменённых потоков, сохранённые версии остальных, удаления без XML-писателя')]
CONTRACTS += [('xml_git','source_reference','Имя source_branch: storage/incoming либо refs/heads/storage/incoming','Проверенный полный ref ветки; неверные и зарезервированные имена отвергаются до записи Git')]
CONTRACTS += [('xml_git','record_source','Проверенные XML-файлы полученной версии и состояние кэша','Один коммит серверной версии; повтор использует существующий коммит')]
CONTRACTS += [('xml_git','reconcile','Кэш, исходная и локальная XML-папки, ibcmd-rs','Коммит версии хранилища, рабочая копия слияния либо отчёт о конфликтах')]


PURPOSES['object_xml_changes'] = 'Читаемое сравнение выбранного объекта через ibcmd-rs objects export: отдельные нативные строки корня, предков и объекта; XML-свойства, формы и BSL, без полного CF и собственного декодера.'
PURPOSES['object_view_context'] = 'Чтение коллекций и UUID-ссылок для адресного контекста просмотра; разрешение имён детей из исторических описаний в XML ibcmd-rs, без записи нативных свойств.'
PURPOSES['object_changes'] = 'Сравнение полных снимков одного UUID: тела и все потоки, нативный текстовый diff и сохранение непрозрачных двоичных данных без XML-компилятора.'
PURPOSES['ИсторияИзменений'] = 'Классификация создания, изменения и удаления любого класса объектов; сравнение свойств описания до и после.'
CONTRACTS += [('object_changes', 'compare', 'UUID и полные снимки before/after; отсутствие стороны означает создание/удаление', 'Изменённые тела/потоки: нативные тексты, diff, Base64, размеры и SHA-256; без сети')]
CONTRACTS += [('object_xml_changes', 'compare', 'UUID, путь ibcmd-rs, платформа, снимки объекта/предков/детей before и after', 'Представление available: выбранные XML/BSL/двоичные файлы, diff и пути свойств было/стало; unavailable с причиной при неполном экспорте')]
CONTRACTS += [('object_view_context', 'plan', 'Нативное тело, UUID, класс и платформа; например корень со списком языков и UUID основного языка', 'Именованные коллекции с UUID детей отдельно от структурных UUID-ссылок; нужен снимок основного языка, для прочих детей достаточно исторических имён')]
CONTRACTS += [('object_view_context', 'bind_children', 'XML ibcmd-rs, план коллекций тела и описания детей на момент версии', 'Полные имена дочерних коллекций в XML при неизменных свойствах и inline-детях; отсутствие имени или противоречие класса/родителя — ошибка')]


CONTRACTS += [('КлиентХранилища', 'ПоместитьПакет', 'Любой ПакетПомещенияОбъекта, комментарий и UUID подключения', 'Единая проверка источников/захватов, один commitObjects, подтверждение описаний и удалений; группа → массив, одиночное изменение/создание → объект, удаление → родитель')]


PURPOSES.update({
 'commit_artifacts': 'Неизменяемый подготовленный пакет, план с SHA256 одобрения, локальный журнал единственной попытки и проверка нативного содержимого после помещения.',
 'ПомещениеАгента': 'CLI/MCP-помещение: восстановление проверенного пакета, контроль источников, существующий жизненный цикл захватов, одно помещение, адресное чтение результата и обновление основы.',
 'resource_limits': 'Проверяемые лимиты процесса из профиля/окружения, области настроек и потоковые хеши файлов.',
 'native_storage_file': 'Проверенный файловый индекс нативного контейнера, ленивые чтения записей и запись контейнера без общего буфера.',
 'file_exchange': 'Потоковый HTTP/TCP-приём, проверка framing/XML/base64, публикация файла и необязательный CRS_RPC_TRACE с именами RPC/размерами без URL, авторизации и содержимого.',
 'ОграниченияДанных': 'Положительные лимиты байтов из той же политики процесса, что использует Python.',
 'module_commit': 'Адресная компиляция одного существующего codec=Module по полному снимку: фрагмент CF для ibcmd overlay, проверка BSL/соседних данных, обычный общий пакет без полной конфигурации.',
 'crs_mcp': 'Точка запуска MCP stdio-сервера поверх JSON CLI.',
 'agent_mcp': 'Каталог MCP-инструментов, JSON-RPC lifecycle и очередь CLI; помещение конфигурации и запись пользователей включаются отдельными флагами.',
 'crs': 'Точка запуска JSON CLI из любой рабочей папки.',
 'agent_cli': 'Проверка JSON и профилей, запуск OneScript без секретов в аргументах, поиск по актуальным описаниям, читаемые файлы и review локального пакета.',
 'cli_bridge': 'JSON-мост к КлиентХранилища: чтение, локальная подготовка, отдельное исполнение одобренных помещений и операций пользователей.',
})
CONTRACTS += [
 ('commit_artifacts', 'make_plan', 'prepared_directory, comment/label и именованный профиль; только чтение хранилища', 'plan_file/plan_sha256 с хешами packet/prepared/review, UUID хранилища, версиями, захватами и конфликтами'),
 ('commit_artifacts', 'execute', 'plan_file, approved_plan_sha256, execute=true и тот же профиль', 'Сохранённый результат единственной попытки; при неопределённости только status, без повторной отправки'),
 ('ПомещениеАгента', 'Обработать', 'Внутренний commit.inspect/commit.execute с проверенными файлами подготовки и плана', 'Текущее состояние либо одно помещение через общий клиент, проверка содержимого возвращённой версии и завершение новых захватов'),
 ('file_exchange', 'run', 'mode=exchange/version, URL, файл XML-запроса, новый путь результата; политика лимитов процесса', 'Малый JSON с code/file/bytes/sha256; тело принимается блоками, version проверяет полный контейнер до публикации'),
 ('native_storage_file', 'FileStorage.__init__', 'Путь нативного контейнера', 'Проверенный SHA1-индекс и ленивые записи, без чтения всего файла в память'),
 ('КлиентХранилища', 'ПолучитьПакетТекущейВерсииВФайл', 'Новый путь двоичного файла и Python', 'Проверенный полный контейнер и UUID версии; потоковое XML/base64-декодирование, отказ/удаление при гонке версии'),
 ('module_commit', 'prepare', 'Полный снимок одного UUID, исходное описание, точный module_path, полный BSL и compiler={backend:ibcmd,executable}; необязательный ожидаемый SHA256 исходного текста', 'No-op без data либо один обычный пакет с единственным изменённым модулем; тело/граф/версии прочих потоков сохранены, review с diff и хешами'),
 ('КлиентХранилища', 'ПодготовитьМодульОбъекта', 'Актуальное описание, Ext/ManagerModule.bsl, полный текст, настройки ibcmd, Python; необязательные отчёт и ожидаемый SHA256 исходного BSL', 'ПакетПомещенияОбъекта или Неопределено; адресные чтения, проверки версии до/после, без захвата и записи'),
 ('agent_mcp', 'CLIRunner.__call__', 'Проверяемый CLI JSON-запрос из tools/call; фиксированные config/workspace процесса', 'JSON CLI в structuredContent и content; ошибки CLI → isError, неизвестный результат записи → outcome_unknown'),
 ('agent_cli', 'main', 'CONFIG и один UTF-8 JSON-запрос: чтение, подготовка, план или одобренная запись', 'Один JSON в stdout, exit code 0/1; запись конфигурации только changes.commit с хешем плана и execute=true'),
 ('cli_bridge', 'ВыполнитьЗапрос', 'Проверенный JSON и профиль; пароли только через имена переменных окружения', 'Структура результата CRS API; для changes.prepare — путь packet.bin и план без записи на сервер'),
 ('cli_bridge', 'Пользователи', 'users.list/plan/apply; для записи execute=true и точное expected состояние', 'Проекция без секретов: роль и исходная маска rights; план или подтверждённое изменение'),
]


def inventory(root=ROOT):
    modules = {}
    for path in sorted([*(root / 'src' / 'Сериализация').glob('*.py'),
                        root/'src/agent_cli.py', root/'tools/crs.py',
                        root/'src/agent_mcp.py', root/'tools/crs_mcp.py']):
        modules['python:' + path.stem] = dict(
            name=path.stem, language='Python', path=path.relative_to(root).as_posix())
    for path in sorted([*(root / 'src' / 'Классы').glob('*.os'),
                        *(root / 'src' / 'Модули').glob('*.os'), root/'src/cli_bridge.os']):
        modules['onescript:' + path.stem] = dict(
            name=path.stem, language='OneScript', path=path.relative_to(root).as_posix())
    for module in modules.values():
        if module['name'] not in PURPOSES:
            raise ValueError('Describe new module: ' + module['name'])
        module['purpose'] = PURPOSES[module['name']]
    return modules


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted(node.value)
        return parent + '.' + node.attr if parent else None
    return None


def extract(root=ROOT):
    modules = inventory(root)
    imports, calls = set(), {}

    def call(caller, callee, function):
        if callee in modules and caller != callee:
            calls.setdefault((caller, callee), set()).add(function)

    aliases = {entry.get('name'): 'onescript:' + Path(entry.get('file')).stem
               for entry in E.parse(root / 'lib.config').getroot()}
    for key, module in modules.items():
        text = (root / module['path']).read_text(encoding='utf-8-sig')
        if module['language'] == 'Python':
            tree = ast.parse(text)
            bindings = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target = 'python:' + alias.name
                        if target in modules:
                            bindings[alias.asname or alias.name] = (target, '')
                            imports.add((key, target))
                elif isinstance(node, ast.ImportFrom):
                    target = 'python:' + str(node.module)
                    if target in modules:
                        imports.add((key, target))
                        for alias in node.names:
                            bindings[alias.asname or alias.name] = (target, alias.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = dotted(node.func)
                    if name and name.split('.')[0] in bindings:
                        target, prefix = bindings[name.split('.')[0]]
                        suffix = name.partition('.')[2]
                        call(key, target, '.'.join(part for part in (prefix, suffix) if part))
        else:
            # Strip comments and string literals before finding named module calls.
            code = re.sub(r'//[^\r\n]*|"(?:""|[^"])*"', ' ', text)
            for name, function in re.findall(r'([\wА-Яа-яЁё]+)\.([\wА-Яа-яЁё]+)\s*\(', code):
                if name in aliases:
                    call(key, aliases[name], function)
            for name in re.findall(r'Новый\s+([\wА-Яа-яЁё]+)', code):
                if name in aliases:
                    call(key, aliases[name], 'ПриСозданииОбъекта')
            for script in re.findall(r'"([a-z_]+)\.py"', text):
                call(key, 'python:' + script, 'JSON CLI')
    call('python:agent_cli', 'onescript:cli_bridge', 'JSON через subprocess')
    call('python:agent_mcp', 'python:crs', 'JSON CLI через subprocess')
    for method in re.findall(r'Клиент\.([\wА-Яа-яЁё]+)\s*\(', (root/'src/cli_bridge.os').read_text(encoding='utf-8-sig')):
        call('onescript:cli_bridge', 'onescript:КлиентХранилища', method)
    contracts = []
    for name, function, inputs, outputs in CONTRACTS:
        if 'onescript:' + name in modules:
            key='onescript:' + name
            text=(root/modules[key]['path']).read_text(encoding='utf-8-sig')
            matches=re.findall(r'^\s*(?:Функция|Процедура)\s+'+re.escape(function)+r'\s*\(([^\r\n]*)\)',text,re.MULTILINE|re.IGNORECASE)
            if len(matches)!=1:raise ValueError('Example function is missing: '+name+'.'+function)
            contracts.append(dict(module=key,function=function,signature=function+'('+matches[0]+')',inputs=inputs,outputs=outputs))
            continue
        path = root / modules['python:' + name]['path']
        scopes = [ast.parse(path.read_text(encoding='utf-8-sig'))]
        for part in function.split('.'):
            scopes = [node for scope in scopes for node in scope.body
                      if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == part]
        matches = [node for node in scopes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(matches) != 1:
            raise ValueError('Example function is missing: ' + name + '.' + function)
        contracts.append(dict(module='python:' + name, function=function,
                              signature=function + '(' + ast.unparse(matches[0].args) + ')',
                              inputs=inputs, outputs=outputs))
    return dict(modules=modules, contracts=contracts, metadata_routes=metadata_structure.stored_routes(),
                imports=[dict(caller=a, callee=b) for a, b in sorted(imports)],
                calls=[dict(caller=a, callee=b, functions=sorted(names))
                       for (a, b), names in sorted(calls.items())])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    data = extract()
    outputs = {
        ROOT / 'docs' / 'module-map.json': json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        ROOT / 'docs' / 'module-map.md': markdown(data),
    }
    for path, text in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8-sig') != text:
                raise SystemExit('Module map is out of date: ' + str(path))
        else:
            path.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
    print('Module map: ' + str(len(data['modules'])) + ' modules, '
          + str(len(data['calls'])) + ' call edges.')


def transformation_examples():
    return """## Пример всей цепочки

```text
исходная XML-папка + целевая XML-папка + актуальный CF
  → configuration_export.plan: операции и отпечатки
  → ibcmd_backend: cf export --index → полные изменённые файлы → cf load --base
    при отказе cf load → cf bootstrap --base-free → служебные заголовки исходного CF
    оба пути → обратная выгрузка → проверка полного состава и содержимого файлов
  → compiled_metadata: проверки UUID, типов и привязок → ObjectContent
  → configuration_commit: версии и граф
  → packet_builder.assemble: bytes → Base64 data
  → OneScript ПакетПомещенияОбъекта → ПоместитьПакет → HTTP/TCP
```

Например, изменение Catalogs/Items.xml и Catalogs/Items/Forms/Main/Ext/Form.xml
даёт два ObjectContent и один пакет помещения. Нативные тела и поток формы
получены из CF ibcmd-rs. CRS не преобразует XML-свойства в нативные слоты.
"""


def markdown(data):
    modules=data['modules'];incoming={key:set() for key in modules};outgoing={key:set() for key in modules}
    for edge in data['calls']:
        incoming[edge['callee']].add(edge['caller']);outgoing[edge['caller']].add(edge['callee'])
    def names(keys):return ', '.join('`'+modules[key]['name']+'`' for key in sorted(keys)) or '—'
    lines=['# Карта модулей','','Генератор: `python tools/build_module_map.py`; проверка: `--check`.','',
        '```mermaid','flowchart TD',
        ' MCP[tools/crs_mcp.py: MCP stdio] --> Adapter[agent_mcp: инструменты и очередь]',
        ' Adapter --> CLI[tools/crs.py: JSON CLI]',
        ' CLI --> Agent[agent_cli: профили и результаты]',
        ' Agent --> CliBridge[cli_bridge: команды агента]',
        ' CliBridge --> Client[КлиентХранилища]',
        ' Client --> FileIO[file_exchange: HTTP/TCP в файл и base64 по блокам]',
        ' FileIO --> NativeFile[native_storage_file: проверяемый индекс на диске]',
        ' NativeFile --> Cache',
        ' Limits[resource_limits и ОграниченияДанных] -.-> FileIO',
        ' Limits -.-> Cache',
        ' Client --> ModuleCommit[module_commit: один BSL-модуль по снимку]',
        ' ModuleCommit --> Compiler',
        ' ModuleCommit --> ModulePacket[packet_builder: общий пакет]',
        ' Client --> Bridge[СериализаторОбъектаХранилища: JSON-мост]',
        ' Bridge --> Commit[configuration_commit]',' Bridge --> Cache[repository_cache: выборочное обновление CF]',
        ' Cache --> Basis[repository_baseline: XML-основа и рабочая папка]',
        ' Basis --> Compiler[ibcmd_backend]',
        ' Cache --> XMLGit[xml_git: необязательные ветка хранилища и Git merge]',
        ' XMLGit --> Commit',' Cache --> Compiler[ibcmd_backend]',' Commit --> Compiler',
        ' Compiler --> External[ibcmd-rs: CF ↔ XML]',' Compiler --> Delta[compiled_image: различие двух CF]',' Delta --> Commit',' Compiler --> Checks[compiled_metadata]',
        ' Commit --> Creation[compiled_creation]',' Creation --> Facts[compiled_graph: факты идентичности]',' Facts --> Readers',
        ' Commit --> Types[compiled_graph.TypeIndex: имена типов и владельцы]',' Types --> Facts',
        ' Creation --> Links[compiled_dependencies: общий граф связей]',' Checks --> Links',' Links --> Types',
        ' Checks --> Readers[Нативные читатели]',' Checks --> Content[ObjectContent]',
        ' Content --> Commit',' Commit --> Packet[packet_builder]',' Packet --> Client',
        ' Client --> Transport[ТранспортХранилища]',' Transport --> HTTP[HTTP хранилища]',' Transport --> TCP[TCP хранилища]',
        ' Compiler --> CF[cf_container: контейнер CF]' ,'```','',
        'ibcmd-rs выполняет всё преобразование XML в нативное содержимое. CRS отвечает за протокол хранилища, версии, граф и проверки. '+
        'Контейнер CF читает и записывает встроенный cf_container; служебный текст формирует native_metadata. Внешних Python-зависимостей и XML-преобразователей проекта больше нет.','',
        transformation_examples(),'## Контракты','','| Функция | Вход | Выход |','| --- | --- | --- |']
    for row in data['contracts']:
        lines.append('| `'+modules[row['module']]['name']+'.'+row['signature']+'` | '+row['inputs']+' | '+row['outputs']+' |')
    for language in ['OneScript','Python']:
        lines+=['','## '+language,'','| Модуль | Назначение | Вызывается из | Вызывает |','| --- | --- | --- | --- |']
        for key,module in sorted(modules.items()):
            if module['language']==language:
                lines.append('| ['+module['name']+'](../'+module['path']+') | '+module['purpose']+' | '+names(incoming[key])+' | '+names(outgoing[key])+' |')
    routes=data['metadata_routes'];missing=[row for row in routes if not row['class_id']]
    lines+=['','## Коллекции дерева конфигурации','',
        'Схема содержит '+str(len(routes))+' маршрутов отдельно хранимых детей, достижимых от Configuration. '+
        'Это карта структуры, а не перечень сквозных проверок ibcmd-rs. Внешние обработки и отчёты в это дерево не входят.','',
        '| Родитель | Коллекции отдельно хранимых детей |','| --- | --- |']
    for owner in sorted({row['owner'] for row in routes}):
        lines.append('| `'+owner+'` | '+', '.join('`'+row['collection']+'`'+(' (UUID из CF)' if not row['class_id'] else '') for row in routes if row['owner']==owner)+' |')
    lines+=['',str(len(routes)-len(missing))+' маршрутов имеют UUID класса в карте схемы; '+str(len(missing))+
        ' определяют его из единственной нативной коллекции с точно совпадающим набором дочерних UUID. '+
        'Для пустой коллекции класс не угадывается. Для всех маршрутов итоговые идентификаторы и состав детей проверяются по CF.','',
        'Связи извлечены статически; динамические вызовы методов экземпляров могут отсутствовать. '+
        'Полный список импортов и вызовов — в [module-map.json](module-map.json). '+
        'JSON-профили используются читателями для проверки нативных структур; они не обозначают поддержку записи через ibcmd-rs.','']
    return '\n'.join(lines)


if __name__=='__main__':main()
