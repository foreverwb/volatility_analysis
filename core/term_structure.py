"""
期限结构分析模块 - v2.5.0
Term Structure Pattern Recognition

识别6种典型期限结构形态：
1. 📉 短期倒挂 - 买波信号
2. 📈 正常陡峭 - 卖波信号  
3. 🔥 短期低位 - 强买波信号
4. ⚠️ 全面倒挂 - 等待回归
5. 📊 中期突起 - 避开中期
6. 📉 远期过高 - 卖出远期
"""
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class TermStructurePattern:
    """期限结构形态"""
    pattern_type: str       # 形态类型
    pattern_name: str       # 形态名称
    signal: str             # 交易信号
    confidence: str         # 置信度（高/中/低）
    description: str        # 详细描述
    strategy: str           # 策略建议
    risk_warning: str       # 风险提示
    slope_short: float      # 短期斜率 (IV30 - IV7)
    slope_mid: float        # 中期斜率 (IV60 - IV30)
    slope_long: float       # 长期斜率 (IV90 - IV60)
    iv_curve: List[float]   # IV曲线 [7D, 30D, 60D, 90D]


def analyze_term_structure(
    iv_7d: Optional[float],
    iv_30d: Optional[float],
    iv_60d: Optional[float],
    iv_90d: Optional[float],
    threshold: float = 2.0  # 斜率判断阈值（百分点）
) -> Optional[TermStructurePattern]:
    """
    分析期限结构形态
    
    Args:
        iv_7d: 7天期IV（%）
        iv_30d: 30天期IV（%）
        iv_60d: 60天期IV（%）
        iv_90d: 90天期IV（%）
        threshold: 斜率判断阈值（默认2%）
        
    Returns:
        TermStructurePattern 对象，数据不足返回 None
    """
    # ========== 数据验证 ==========
    if not all(isinstance(iv, (int, float)) for iv in [iv_7d, iv_30d, iv_60d, iv_90d]):
        return None
    
    if any(iv is None or iv <= 0 for iv in [iv_7d, iv_30d, iv_60d, iv_90d]):
        return None
    
    # ========== 计算斜率 ==========
    slope_short = iv_30d - iv_7d   # 短期斜率（7D → 30D）
    slope_mid = iv_60d - iv_30d     # 中期斜率（30D → 60D）
    slope_long = iv_90d - iv_60d    # 长期斜率（60D → 90D）
    
    iv_curve = [iv_7d, iv_30d, iv_60d, iv_90d]
    
    # ========== 形态识别 ==========
    
    # 1️⃣ 短期倒挂：IV_7D > IV_30D（至少超过阈值）
    if slope_short < -threshold:
        intensity = abs(slope_short)
        
        confidence = "高" if intensity > threshold * 2 else "中"
        
        return TermStructurePattern(
            pattern_type="SHORT_BACKWARDATION",
            pattern_name="📉 短期倒挂",
            signal="买波信号",
            confidence=confidence,
            description=f"短期IV高于中期 {intensity:.1f}%，通常由即将到来的事件（财报、FDA决定等）引起",
            strategy="买入短期期权（7-14天），利用事件后IV回落获利；或做日历价差（卖远买近）",
            risk_warning="事件落地后IV可能暴跌，需设置止损；如果事件取消或延期，倒挂可能持续",
            slope_short=slope_short,
            slope_mid=slope_mid,
            slope_long=slope_long,
            iv_curve=iv_curve
        )
    
    # 2️⃣ 全面倒挂：所有斜率均为负（市场恐慌）
    if all(s < -threshold/2 for s in [slope_short, slope_mid, slope_long]):
        return TermStructurePattern(
            pattern_type="FULL_BACKWARDATION",
            pattern_name="⚠️ 全面倒挂",
            signal="等待回归",
            confidence="高",
            description=f"整条曲线倒挂（短期IV {iv_7d:.1f}% > 远期IV {iv_90d:.1f}%），通常出现在市场极度恐慌时",
            strategy="等待IV回归正常；或卖出短期跨式/宽跨式，买入远期对冲",
            risk_warning="极端行情，流动性可能枯竭；倒挂可能持续数周；需严格控制仓位",
            slope_short=slope_short,
            slope_mid=slope_mid,
            slope_long=slope_long,
            iv_curve=iv_curve
        )
    
    # 3️⃣ 中期突起：IV_30D 或 IV_60D 明显高于两端
    mid_peak_30 = (iv_30d > iv_7d + threshold) and (iv_30d > iv_60d + threshold/2)
    mid_peak_60 = (iv_60d > iv_30d + threshold) and (iv_60d > iv_90d + threshold/2)
    
    if mid_peak_30 or mid_peak_60:
        peak_day = "30天" if mid_peak_30 else "60天"
        peak_iv = iv_30d if mid_peak_30 else iv_60d
        
        return TermStructurePattern(
            pattern_type="MID_HUMP",
            pattern_name="📊 中期突起",
            signal="避开中期",
            confidence="中",
            description=f"{peak_day}期IV异常高（{peak_iv:.1f}%），可能有预期中的中期事件",
            strategy=f"避免买入{peak_day}期权；做蝶式价差（卖{peak_day}，买两端）；或等待事件明确后再交易",
            risk_warning="事件可能提前或延后；突起可能是定价错误",
            slope_short=slope_short,
            slope_mid=slope_mid,
            slope_long=slope_long,
            iv_curve=iv_curve
        )
    
    # 4️⃣ 远期过高：IV_90D 显著高于 IV_60D
    if slope_long > threshold * 1.5:
        return TermStructurePattern(
            pattern_type="LONG_STEEP",
            pattern_name="📉 远期过高",
            signal="卖出远期",
            confidence="中",
            description=f"远期IV溢价明显（IV_90D {iv_90d:.1f}% vs IV_60D {iv_60d:.1f}%），远期不确定性被高估",
            strategy="卖出90天期权；或做反向日历价差（卖远买近）；备兑策略使用远期合约",
            risk_warning="远期溢价可能来自真实的长期不确定性（如大选、重组）；时间衰减慢",
            slope_short=slope_short,
            slope_mid=slope_mid,
            slope_long=slope_long,
            iv_curve=iv_curve
        )
    
    # 5️⃣ 短期低位：IV_7D 显著低于 IV_30D，且曲线递增
    if (slope_short > threshold * 1.5 and 
        slope_mid > 0 and 
        slope_long >= 0):
        
        discount = iv_30d - iv_7d
        
        return TermStructurePattern(
            pattern_type="SHORT_UNDERVALUED",
            pattern_name="🔥 短期低位",
            signal="强买波信号",
            confidence="高",
            description=f"短期IV被低估 {discount:.1f}%，可能是事件后回落过度或市场忽视短期风险",
            strategy="买入7-14天期权；做正向日历价差（卖远买近）；跨式/宽跨式策略",
            risk_warning="确认没有即将到来的利空事件；低IV可能持续较长时间",
            slope_short=slope_short,
            slope_mid=slope_mid,
            slope_long=slope_long,
            iv_curve=iv_curve
        )
    
    # 6️⃣ 正常陡峭：所有斜率均为正（标准形态）
    if all(s > threshold/3 for s in [slope_short, slope_mid, slope_long]):
        steepness = (iv_90d - iv_7d) / iv_7d * 100  # 陡峭度（%）
        
        confidence = "高" if steepness > 30 else "中"
        
        return TermStructurePattern(
            pattern_type="NORMAL_UPWARD",
            pattern_name="📈 正常陡峭",
            signal="卖波信号",
            confidence=confidence,
            description=f"标准递增曲线（陡峭度 {steepness:.1f}%），市场平静，远期不确定性正常定价",
            strategy="卖出期权获取权利金；铁鹰/铁蝶策略；备兑开仓；卖出跨式/宽跨式",
            risk_warning="突发事件可能打破平静；卖波需设置止损；避免在低IV环境卖波",
            slope_short=slope_short,
            slope_mid=slope_mid,
            slope_long=slope_long,
            iv_curve=iv_curve
        )
    
    # 7️⃣ 其他/平坦：无明显特征
    return TermStructurePattern(
        pattern_type="FLAT_OR_MIXED",
        pattern_name="📊 平坦/混合",
        signal="观望",
        confidence="低",
        description="期限结构无明显特征，可能处于过渡期或定价异常",
        strategy="观望等待更清晰信号；或使用其他指标（IVR、IVRV）辅助判断",
        risk_warning="缺乏方向性指引；可能有定价错误",
        slope_short=slope_short,
        slope_mid=slope_mid,
        slope_long=slope_long,
        iv_curve=iv_curve
    )


def get_term_structure_display(pattern: TermStructurePattern) -> Dict:
    """
    获取前端展示数据
    
    Args:
        pattern: 期限结构形态对象
        
    Returns:
        前端展示数据字典
    """
    return {
        'pattern_name': pattern.pattern_name,
        'signal': pattern.signal,
        'confidence': pattern.confidence,
        'description': pattern.description,
        'strategy': pattern.strategy,
        'risk_warning': pattern.risk_warning,
        'slopes': {
            'short': round(pattern.slope_short, 2),
            'mid': round(pattern.slope_mid, 2),
            'long': round(pattern.slope_long, 2)
        },
        'iv_curve': [round(iv, 1) for iv in pattern.iv_curve],
        'curve_labels': ['7D', '30D', '60D', '90D']
    }


def get_term_structure_color(pattern: TermStructurePattern) -> str:
    """
    获取形态对应的颜色（用于前端显示）
    
    Returns:
        CSS 颜色代码
    """
    color_map = {
        "SHORT_BACKWARDATION": "#FF9500",  # 橙色 - 买波信号
        "FULL_BACKWARDATION": "#FF3B30",   # 红色 - 警告
        "MID_HUMP": "#FFCC00",             # 黄色 - 中性
        "LONG_STEEP": "#5AC8FA",           # 浅蓝 - 卖远期
        "SHORT_UNDERVALUED": "#00C853",    # 绿色 - 强买波
        "NORMAL_UPWARD": "#007AFF",        # 蓝色 - 卖波
        "FLAT_OR_MIXED": "#8E8E93"         # 灰色 - 观望
    }
    return color_map.get(pattern.pattern_type, "#8E8E93")


# ========== 实用工具函数 ==========

def calculate_term_structure_score(pattern: Optional[TermStructurePattern]) -> float:
    """
    计算期限结构对波动评分的修正系数
    
    Args:
        pattern: 期限结构形态
        
    Returns:
        修正系数 (-1.0 到 +1.0)
        - 正值：利好买波
        - 负值：利好卖波
    """
    if pattern is None:
        return 0.0
    
    score_map = {
        "SHORT_BACKWARDATION": +0.6,   # 买波信号
        "SHORT_UNDERVALUED": +0.8,     # 强买波信号
        "NORMAL_UPWARD": -0.5,         # 卖波信号
        "LONG_STEEP": -0.4,            # 卖远期
        "FULL_BACKWARDATION": 0.0,     # 观望
        "MID_HUMP": -0.2,              # 避开中期
        "FLAT_OR_MIXED": 0.0           # 中性
    }
    
    base_score = score_map.get(pattern.pattern_type, 0.0)
    
    # 根据置信度调整
    confidence_multiplier = {
        "高": 1.0,
        "中": 0.7,
        "低": 0.4
    }
    
    return base_score * confidence_multiplier.get(pattern.confidence, 0.5)


def get_term_structure_emoji(pattern: TermStructurePattern) -> str:
    """获取形态对应的 Emoji"""
    emoji_map = {
        "SHORT_BACKWARDATION": "📉",
        "FULL_BACKWARDATION": "⚠️",
        "MID_HUMP": "📊",
        "LONG_STEEP": "📉",
        "SHORT_UNDERVALUED": "🔥",
        "NORMAL_UPWARD": "📈",
        "FLAT_OR_MIXED": "📊"
    }
    return emoji_map.get(pattern.pattern_type, "📊")