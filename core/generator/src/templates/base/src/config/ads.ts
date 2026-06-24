// 激励广告（rewarded video ad）配置 —— 下载高清/去水印的变现门槛。
//
// 设计：
// - ad unit id 由开发者在构建时配置，codegen 从环境变量注入（不硬编码业务真实广告位）。
// - 未配置时 REWARDED_AD_ENABLED=false + 空 ad unit id：运行时必须诚实提示
//   「开发者未配置广告位，暂不可下载高清结果」，绝不假装广告已完成。
// - 该文件可安全随小程序发布：只含广告位 id，不含任何密钥。
//
// 真机要点（微信小程序）：rewarded video ad 需在微信后台「流量主」开通并创建广告位，
// 拿到 adUnitId（形如 adunit-xxxxxxxx）后填入构建环境变量。

export const REWARDED_AD_UNIT_ID = '__REWARDED_AD_UNIT_ID__'
export const REWARDED_AD_ENABLED: boolean = ('__REWARDED_AD_ENABLED__' as string) === 'true'
