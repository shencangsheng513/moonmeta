///|
/// 有理数：TIFF 用它表示时间、GPS 坐标、焦距等。
///
/// 分子分母存成 `Int64` 而不是 `Int`：TIFF 的 RATIONAL 分子是**无符号**
/// 32 位，最大 4294967295，MoonBit 的 `Int` 只有 31 位可用范围，
/// 直接用 `Int` 存会把大分子读成负数。
pub(all) struct Rational {
  num : Int64
  den : Int64
} derive(Debug, Eq)

///|
pub impl Show for Rational with fn output(self : Rational, logger) {
  logger.write_string("\{self.num}/\{self.den}")
}

///|
pub extend Rational with Eq::{not_equal, equal}

///|
pub extend Rational with @debug.Debug::{to_repr}

///|
pub extend Rational with Show::{to_string, output}

///|
/// 转成 `Double`。`den == 0` 时返回 `+inf` 或 `nan`——规范没禁止分母为 0
/// 的文件存在，这里不 panic，交给调用方判断。
pub fn Rational::to_double(self : Rational) -> Double {
  self.num.to_double() / self.den.to_double()
}

///|
/// 一个标签的值。变体与 TIFF 类型码对应，见 `type_size`。
///
/// `Text` 是 ISO-8859-1 逐字节映射（一字节一码点，双向可逆），
/// 不做"认不出来就替换成 `?`"的有损转换——EXIF 的 Make/Model 字段里
/// 出现非 ASCII 是常态，脱敏工具不该在读的阶段就篡改数据。
pub(all) enum TagValue {
  Text(String)
  Shorts(Array[Int])
  Longs(Array[Int64])
  Rationals(Array[Rational])
  Raw(Array[Byte])
} derive(Debug, Eq)

///|
pub impl Show for TagValue with fn output(self : TagValue, logger) {
  match self {
    Text(s) => logger.write_string("\"\{s}\"")
    Shorts(v) => logger.write_string("Shorts(\{v.length()} value(s))")
    Longs(v) => logger.write_string("Longs(\{v.length()} value(s))")
    Rationals(v) => logger.write_string("Rationals(\{v.length()} value(s))")
    Raw(v) => logger.write_string("Raw(\{v.length()} byte(s))")
  }
}

///|
pub extend TagValue with Eq::{not_equal, equal}

///|
pub extend TagValue with @debug.Debug::{to_repr}

///|
pub extend TagValue with Show::{to_string, output}

///|
pub fn TagValue::text(self : TagValue) -> String? {
  match self {
    Text(s) => Some(s)
    _ => None
  }
}

///|
pub fn TagValue::shorts(self : TagValue) -> Array[Int]? {
  match self {
    Shorts(v) => Some(v)
    _ => None
  }
}

///|
pub fn TagValue::rationals(self : TagValue) -> Array[Rational]? {
  match self {
    Rationals(v) => Some(v)
    _ => None
  }
}

///|
/// TIFF 类型码 → 单个组件的字节数；`None` 表示该码没有定义。
///
/// 这个表对**所有**规范类型码都有定义，包括本版本还解不了的 `FLOAT`/`DOUBLE`：
/// 即使不解码，也要先能算出它声明了多少字节，才能判断文件有没有越界。
pub fn type_size(code : Int) -> Int? {
  match code {
    1 => Some(1) // BYTE
    2 => Some(1) // ASCII
    3 => Some(2) // SHORT
    4 => Some(4) // LONG
    5 => Some(8) // RATIONAL
    6 => Some(1) // SBYTE
    7 => Some(1) // UNDEFINED
    8 => Some(2) // SSHORT
    9 => Some(4) // SLONG
    10 => Some(8) // SRATIONAL
    11 => Some(4) // FLOAT
    12 => Some(8) // DOUBLE
    13 => Some(4) // IFD
    _ => None
  }
}

///|
/// 该类型码本版本是否解码。
pub fn type_decodable(code : Int) -> Bool {
  // 11/12/13 先按原样拒绝：浮点要位模式转换，IFD 是指针，都不是"读一个数"。
  code >= 1 && code <= 10
}
