import re
from dataclasses import dataclass

ALERT_TEMPLATE = (
    "🔴 {time} Повітряна тривога в {districts}\n"
    "Слідкуйте за подальшими повідомленнями.\n"
    "{hashtags}"
)

ALERT_CANCELLATION_TEMPLATE = (
    "🟢 {time} Відбій тривоги в {districts}\n"
    "Слідкуйте за подальшими повідомленнями.\n"
    "{hashtags}"
)


_HASHTAG_DROPPED = re.compile(r"[.'’]")
_HASHTAG_UNDERSCORED = re.compile(r"[\s-]+")


def _hashtag(place: str) -> str:
    return "#" + _HASHTAG_UNDERSCORED.sub("_", _HASHTAG_DROPPED.sub("", place))


@dataclass(frozen=True)
class AlertSample:

    regions: tuple[str, ...]

    districts: tuple[str, ...]

    alert_time: str = "12:00"
    cancellation_time: str = "13:00"

    @property
    def id(self) -> str:
        suffix = "-combined" if len(self.districts) > 1 else ""
        return "-".join(self.regions) + suffix

    @property
    def alert_message(self) -> str:
        return self._render(ALERT_TEMPLATE, self.alert_time)

    @property
    def cancellation_message(self) -> str:
        return self._render(ALERT_CANCELLATION_TEMPLATE, self.cancellation_time, end=".")

    def _render(self, template: str, time: str, end: str = "") -> str:
        districts = (
            self.districts[0] + end
            if len(self.districts) == 1
            else "\n" + "\n".join(f"• {place}" for place in self.districts)
        )
        return template.format(
            time=time,
            districts=districts,
            hashtags=" ".join(_hashtag(place) for place in self.districts),
        )


def region_sample(region, district, alert_time="12:00", cancellation_time="13:00"):
    """A post about a single district — the common case."""
    return AlertSample((region,), (district,), alert_time, cancellation_time)


MESSAGES_SAMPLES = (
    # --- Kyiv ---
    region_sample("kyiv", "м. Київ", "04:31", "05:24"),

    # --- Central ---
    region_sample("cherkasy", "Черкаський район", "10:08", "11:06"),
    region_sample("uman", "Уманський район", "19:53", "21:11"),
    region_sample("zvenyhorodka", "Звенигородський район", "17:44", "18:49"),
    region_sample("zolotonosha", "Золотоніський район", "17:17", "18:04"),
    region_sample("chernihiv", "Чернігівський район", "23:47", "00:29"),
    region_sample("kropyvnytskyi", "Кропивницький район", "06:59", "07:42"),
    region_sample("poltava", "Полтавський район", "13:10", "14:41"),
    region_sample("kremenchuk", "Кременчуцький район", "12:57", "14:34"),
    region_sample("vinnytsia", "Вінницький район", "14:34", "16:26"),
    region_sample("zhytomyr", "Житомирський район", "12:44", "13:56"),

    # --- Kyiv region ---
    region_sample("bilatserkva", "Білоцерківський район", "20:26", "21:56"),
    region_sample("bucha", "Бучанський район", "19:53", "20:59"),
    region_sample("fastiv", "Фастівський район", "19:27", "21:02"),

    # --- Northeast ---
    region_sample("kharkiv", "м. Харків", "22:42", "23:18"),
    region_sample("sumy", "Сумський район", "06:12", "06:55"),

    # --- East ---
    region_sample("zaporizhzhia", "м. Запоріжжя", "18:07", "18:47"),
    region_sample("dnipro", "Дніпровський район", "00:21", "01:29"),
    region_sample("kryvyirih", "Криворізький район", "05:03", "06:46"),
    region_sample("kamianske", "Кам'янський район", "03:26", "04:53"),
    region_sample("nikopol", "Нікопольський район", "10:27", "11:30"),

    # --- South ---
    region_sample("kherson", "Херсонський район", "08:44", "09:18"),
    region_sample("mykolaiv", "Миколаївський район", "23:33", "01:21"),
    region_sample("pervomaisk", "Первомайський район", "09:11", "10:07"),
    region_sample("odesa", "Одеський район", "02:16", "03:20"),
    region_sample("izmail", "Ізмаїльський район", "20:17", "21:55"),

    # --- West ---
    region_sample("lviv", "Львівський район", "04:28", "05:45"),
    region_sample("lutsk", "Луцький район", "18:28", "19:59"),
    region_sample("kovel", "Ковельський район", "20:11", "22:10"),
    region_sample("rivne", "Рівненський район", "16:12", "17:44"),
    region_sample("ternopil", "Тернопільський район", "02:19", "03:52"),
    region_sample("khmelnytskyi", "Хмельницький район", "15:59", "16:56"),
    region_sample("ivanofrankivsk", "Івано-Франківський район", "11:29", "12:08"),
    region_sample("uzhhorod", "Ужгородський район", "15:36", "17:26"),
    region_sample("chernivtsi", "Чернівецький район", "11:32", "12:50"),
)

COMBINED_SAMPLES = (
    AlertSample(
        regions=("ivanofrankivsk",),
        districts=(
            "Івано-Франківський район",
            "Коломийський район",
            "Надвірнянський район",
            "Калуський район",
            "Верховинський район",
        ),
        alert_time="15:59",
        cancellation_time="16:56",
    ),

    AlertSample(
        regions=("dnipro", "kryvyirih", "kamianske", "nikopol"),
        districts=(
            "Дніпровський район",
            "Криворізький район",
            "Кам'янський район",
            "Нікопольський район",
            "Синельниківський район",
        ),
        alert_time="00:21",
        cancellation_time="01:29",
    ),
    AlertSample(
        regions=("kyiv", "bilatserkva", "bucha", "fastiv"),
        districts=(
            "м. Київ",
            "Білоцерківський район",
            "Бучанський район",
            "Фастівський район",
        ),
        alert_time="04:31",
        cancellation_time="05:24",
    ),
)

ALL_SAMPLES = MESSAGES_SAMPLES + COMBINED_SAMPLES
