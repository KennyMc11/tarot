# api_key_pool.py
import asyncio
import random
from typing import List, Optional
from datetime import datetime, timedelta
from collections import deque

class APIKeyPool:
    """Пул API ключей с балансировкой нагрузки и автоматическим отключением проблемных ключей"""
    
    def __init__(self, api_keys: List[str]):
        self.keys = []
        for key in api_keys:
            self.keys.append({
                'key': key,
                'is_active': True,
                'fail_count': 0,
                'last_fail_time': None,
                'total_requests': 0,
                'total_fails': 0
            })
        self._current_index = 0
    
    def get_next_key(self) -> Optional[str]:
        """Возвращает следующий активный ключ (round-robin)"""
        if not self._has_active_keys():
            # Если все ключи отключены, пробуем их восстановить
            self._reset_failed_keys()
            if not self._has_active_keys():
                return None
        
        # Находим следующий активный ключ
        attempts = 0
        while attempts < len(self.keys):
            self._current_index = (self._current_index + 1) % len(self.keys)
            if self.keys[self._current_index]['is_active']:
                self.keys[self._current_index]['total_requests'] += 1
                return self.keys[self._current_index]['key']
            attempts += 1
        
        return None
    
    def get_random_key(self) -> Optional[str]:
        """Возвращает случайный активный ключ"""
        active_keys = [k for k in self.keys if k['is_active']]
        if not active_keys:
            self._reset_failed_keys()
            active_keys = [k for k in self.keys if k['is_active']]
            if not active_keys:
                return None
        
        selected = random.choice(active_keys)
        selected['total_requests'] += 1
        return selected['key']
    
    def report_failure(self, api_key: str):
        """Сообщает о неудаче с ключом"""
        for key_info in self.keys:
            if key_info['key'] == api_key:
                key_info['fail_count'] += 1
                key_info['total_fails'] += 1
                key_info['last_fail_time'] = datetime.now()
                # Отключаем ключ после 3 неудач подряд
                if key_info['fail_count'] >= 3:
                    key_info['is_active'] = False
                    print(f"⚠️ API ключ {api_key[:10]}... отключен (3+ ошибок)")
                break
    
    def report_success(self, api_key: str):
        """Сообщает об успехе с ключом"""
        for key_info in self.keys:
            if key_info['key'] == api_key:
                key_info['fail_count'] = 0
                # Автоматически восстанавливаем ключ после успеха, если был отключен
                if not key_info['is_active']:
                    key_info['is_active'] = True
                    print(f"✅ API ключ {api_key[:10]}... восстановлен")
                break
    
    def _has_active_keys(self) -> bool:
        return any(k['is_active'] for k in self.keys)
    
    def _reset_failed_keys(self):
        """Восстанавливает отключенные ключи после паузы"""
        now = datetime.now()
        for key_info in self.keys:
            if not key_info['is_active'] and key_info['last_fail_time']:
                # Восстанавливаем через 5 минут
                if now - key_info['last_fail_time'] > timedelta(minutes=5):
                    key_info['is_active'] = True
                    key_info['fail_count'] = 0
                    print(f"🔄 API ключ {key_info['key'][:10]}... восстановлен после паузы")
    
    def get_stats(self) -> dict:
        """Возвращает статистику по ключам"""
        return {
            'total_keys': len(self.keys),
            'active_keys': sum(1 for k in self.keys if k['is_active']),
            'total_requests': sum(k['total_requests'] for k in self.keys),
            'total_fails': sum(k['total_fails'] for k in self.keys),
            'keys': [{
                'key': k['key'][:10] + '...',
                'is_active': k['is_active'],
                'fails': k['total_fails'],
                'requests': k['total_requests']
            } for k in self.keys]
        }