#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CosyVoice 各版本通用函数
支持：CosyVoice (v1)、CosyVoice2 (v2)、CosyVoice3 (v3)
"""

import os
import sys
import torch
import torchaudio
from typing import List, Optional, Union, Dict, Any

# 添加第三方依赖路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 获取当前脚本所在的绝对目录（即E:\Kai\kai_agent\voice）
SCRIPT_ROOT = os.path.dirname(os.path.abspath(__file__))
# 拼接得到CosyVoice项目根目录的绝对路径
cosyvoice_path = os.path.join(SCRIPT_ROOT, "CosyVoice")
# 拼接得到第三方依赖库的绝对路径
matcha_tts_path = os.path.join(cosyvoice_path, "third_party", "Matcha-TTS")
# 将两个路径加入Python模块搜索路径
sys.path.append(cosyvoice_path)
sys.path.append(matcha_tts_path)
print("已配置的CosyVoice路径：", cosyvoice_path)
print("已配置的Matcha-TTS路径：", matcha_tts_path)
from cosyvoice.cli.cosyvoice import CosyVoice


# ==================== 模型加载函数 ====================

def load_cosyvoice_model(
    model_dir: str,
    version: str = 'v1',
    **kwargs
) -> Any:
    """
    通用的 CosyVoice 模型加载函数
    
    Args:
        model_dir: 模型目录路径
        version: 模型版本，可选 'v1', 'v2', 'v3'
        **kwargs: 额外参数，不同版本有不同含义：
            - v2: load_jit=False, load_trt=False, load_vllm=False, fp16=False
            - v3: 根据具体实现可能需要额外参数
    
    Returns:
        加载好的模型实例
    
    Examples:
        >>> # 加载第一代模型
        >>> model = load_cosyvoice_model('pretrained_models/CosyVoice-300M', 'v1')
        >>> 
        >>> # 加载第二代模型
        >>> model = load_cosyvoice_model('pretrained_models/CosyVoice2-0.5B', 'v2')
        >>> 
        >>> # 加载第三代模型
        >>> model = load_cosyvoice_model('pretrained_models/Fun-CosyVoice3-0.5B', 'v3')
    """
    
    if version == 'v1':
        from cosyvoice.cli.cosyvoice import CosyVoice
        model = CosyVoice(model_dir)
    
    elif version == 'v2':
        from cosyvoice.cli.cosyvoice import CosyVoice2
        
        # 默认参数（官方推荐）
        load_jit = kwargs.get('load_jit', False)
        load_trt = kwargs.get('load_trt', False)
        load_vllm = kwargs.get('load_vllm', False)
        fp16 = kwargs.get('fp16', False)
        
        model = CosyVoice2(
            model_dir,
            load_jit=load_jit,
            load_trt=load_trt,
            load_vllm=load_vllm,
            fp16=fp16
        )
    
    elif version == 'v3':
        # 尝试多种导入方式
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice3
            model = CosyVoice3(model_dir, **kwargs)
        except (ImportError, AttributeError):
            try:
                from cosyvoice.cli.cosyvoice import AutoModel
                model = AutoModel(model_dir, **kwargs)
            except ImportError:
                raise ImportError(
                    "无法导入 CosyVoice3 或 AutoModel，请检查是否正确安装了 CosyVoice 库"
                )
    
    else:
        raise ValueError(f"不支持的模型版本: {version}，请使用 'v1', 'v2' 或 'v3'")
    
    return model


# ==================== 说话人列表获取函数 ====================

def get_available_speakers(
    model: Any,
    version: str = 'v1'
) -> List[str]:
    """
    获取模型可用的说话人列表（通用函数）
    
    Args:
        model: 已加载的模型实例
        version: 模型版本，可选 'v1', 'v2', 'v3'
    
    Returns:
        说话人名称列表
    
    Examples:
        >>> model = load_cosyvoice_model('pretrained_models/CosyVoice-300M-SFT', 'v1')
        >>> speakers = get_available_speakers(model, 'v1')
        >>> print(speakers)  # ['中文男', '中文女', '英文男', '英文女', ...]
    """
    
    if version == 'v1':
        # 第一代模型使用 list_available_spks()
        if hasattr(model, 'list_available_spks'):
            return model.list_available_spks()
        else:
            # 部分 v1 模型可能没有此方法
            return []
    
    elif version == 'v2':
        # 第二代模型可能有类似方法，但名称可能不同
        if hasattr(model, 'list_available_spks'):
            return model.list_available_spks()
        elif hasattr(model, 'get_speakers'):
            return model.get_speakers()
        else:
            # 返回一个默认说话人列表
            return ['中文女', '中文男']
    
    elif version == 'v3':
        # 第三代模型获取说话人列表的方式
        if hasattr(model, 'list_available_spks'):
            return model.list_available_spks()
        elif hasattr(model, 'get_speakers'):
            return model.get_speakers()
        elif hasattr(model, 'speakers'):
            return list(model.speakers) if isinstance(model.speakers, dict) else []
        else:
            return ['default']
    
    else:
        raise ValueError(f"不支持的模型版本: {version}")


# ==================== SFT 推理函数 ====================

def inference_sft(
    model: Any,
    text: str,
    speaker: str,
    version: str = 'v1',
    stream: bool = False,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    使用 SFT 模式进行语音合成的通用函数
    
    Args:
        model: 已加载的模型实例
        text: 要合成的文本
        speaker: 说话人名称
        version: 模型版本，可选 'v1', 'v2', 'v3'
        stream: 是否流式输出
        **kwargs: 额外参数
    
    Returns:
        包含音频数据和元信息的列表
    
    Examples:
        >>> model = load_cosyvoice_model('pretrained_models/CosyVoice-300M-SFT', 'v1')
        >>> results = inference_sft(model, '你好，我是小Kai。', '中文女', 'v1')
        >>> for i, result in enumerate(results):
        >>>     torchaudio.save(f'output_{i}.wav', result['tts_speech'], 22050)
    """
    
    results = []
    
    if version == 'v1':
        # 第一代模型 SFT 推理
        if hasattr(model, 'inference_sft'):
            for result in model.inference_sft(text, speaker, stream=stream, **kwargs):
                results.append(result)
        else:
            # 如果模型不支持 SFT，尝试使用 inference
            for result in model.inference(text, speaker, stream=stream, **kwargs):
                results.append(result)
    
    elif version == 'v2':
        # 第二代模型 SFT 推理（可能使用不同的方法名）
        if hasattr(model, 'inference_sft'):
            for result in model.inference_sft(text, speaker, stream=stream, **kwargs):
                results.append(result)
        elif hasattr(model, 'inference'):
            # CosyVoice2 可能使用 inference 方法
            for result in model.inference(text, speaker, stream=stream, **kwargs):
                results.append(result)
        else:
            raise AttributeError("模型没有 SFT 推理方法")
    
    elif version == 'v3':
        # 第三代模型 SFT 推理
        if hasattr(model, 'inference_sft'):
            for result in model.inference_sft(text, speaker, stream=stream, **kwargs):
                results.append(result)
        elif hasattr(model, 'inference'):
            for result in model.inference(text, speaker, stream=stream, **kwargs):
                results.append(result)
        else:
            raise AttributeError("模型没有 SFT 推理方法")
    
    else:
        raise ValueError(f"不支持的模型版本: {version}")
    
    return results
