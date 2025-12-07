"""配置模块测试"""

from config import Config


class TestConfig:
    """配置类测试"""

    def test_config_has_required_attributes(self):
        """测试配置包含必需的属性"""
        assert hasattr(Config, "BOT_TOKEN")
        assert hasattr(Config, "LOG_LEVEL")
        assert hasattr(Config, "DATABASE_URL")
        assert hasattr(Config, "DELETE_CONFIG")
        assert hasattr(Config, "PERMISSIONS")
        assert hasattr(Config, "BLACKLIST_CONFIG")

    def test_delete_config_structure(self):
        """测试删除配置结构"""
        assert isinstance(Config.DELETE_CONFIG, dict)
        assert "auto_delete_spam" in Config.DELETE_CONFIG
        assert "warn_before_delete" in Config.DELETE_CONFIG

    def test_blacklist_config_structure(self):
        """测试黑名单配置结构"""
        assert isinstance(Config.BLACKLIST_CONFIG, dict)
        assert "auto_ban_on_blacklist" in Config.BLACKLIST_CONFIG
        assert "ban_duration" in Config.BLACKLIST_CONFIG
        assert "log_actions" in Config.BLACKLIST_CONFIG

    def test_permissions_config_structure(self):
        """测试权限配置结构"""
        assert isinstance(Config.PERMISSIONS, dict)
        assert "admin_only_commands" in Config.PERMISSIONS
        assert isinstance(Config.PERMISSIONS["admin_only_commands"], list)

    def test_private_forward_config(self):
        """测试私聊转发配置"""
        assert hasattr(Config, "PRIVATE_FORWARD_CONFIG")
        assert isinstance(Config.PRIVATE_FORWARD_CONFIG, dict)
        assert "enabled" in Config.PRIVATE_FORWARD_CONFIG
        assert "admin_user_ids" in Config.PRIVATE_FORWARD_CONFIG
