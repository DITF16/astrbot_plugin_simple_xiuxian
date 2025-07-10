import time
import random
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core import AstrBotConfig
from astrbot.core.star import StarTools


@register(
    "astrbot_plugin_simple_xiuxian",
    "DITF16",
    "一个比较简单的修仙模拟器游戏",
    "1.1",
    "https://github.com/DITF16/astrbot_plugin_simple_xiuxian"
)
class XiuXianPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 用于存储重置确认信息，键是 user_id，值是请求时间戳
        self.reset_confirmations = {}
        self.REALM_CONFIG = [
            {"name": "炼气期", "levels": 10, "exp_base": 100, "display": lambda l: f"第{l}层"},
            {"name": "筑基境", "levels": 4, "exp_base": 2000,
             "display": lambda l: ["初期", "中期", "后期", "圆满"][l - 1]},
            {"name": "结丹境", "levels": 4, "exp_base": 10000,
             "display": lambda l: ["初期", "中期", "后期", "圆满"][l - 1]},
            {"name": "元婴境", "levels": 4, "exp_base": 50000,
             "display": lambda l: ["初期", "中期", "后期", "圆满"][l - 1]},
            {"name": "化神境", "levels": 4, "exp_base": 250000,
             "display": lambda l: ["初期", "中期", "后期", "圆满"][l - 1]},
            {"name": "炼虚境", "levels": 3, "exp_base": 1000000, "display": lambda l: ["初期", "中期", "后期"][l - 1]},
            {"name": "合体境", "levels": 3, "exp_base": 5000000, "display": lambda l: ["初期", "中期", "后期"][l - 1]},
            {"name": "大乘境", "levels": 3, "exp_base": 20000000, "display": lambda l: ["初期", "中期", "后期"][l - 1]},
            {"name": "渡劫期", "levels": 1, "exp_base": 100000000, "display": lambda l: "渡劫中"},
            {"name": "真仙", "levels": 1, "exp_base": 0, "display": lambda l: "逍遥真仙"},
        ]
        self.SPIRIT_ROOTS = {
            "金": {"rate": 1.5, "desc": "庚金之体，攻击犀利"}, "木": {"rate": 1.4, "desc": "草木之灵，生机勃勃"},
            "水": {"rate": 1.6, "desc": "壬水之躯，防御见长"}, "火": {"rate": 1.8, "desc": "烈火之魂，爆发力强"},
            "土": {"rate": 1.2, "desc": "厚土之身，根基稳固"}, "天": {"rate": 2.5, "desc": "天选之人，万古奇才"},
            "废": {"rate": 0.5, "desc": "凡夫俗子，仙路漫漫"},
        }
        self.EXP_PER_MINUTE = 10
        self.INITIAL_GOLD = 100
        self.EQUIPMENT_SLOTS = ["weapon", "armor", "helmet", "boots", "accessory"]

        self.data_path = StarTools.get_data_dir("astrbot_plugin_simple_xiuxian")
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.db_file = self.data_path / "simple_xiuxian_data.db"
        self._init_database()

        self.config = config
        self.enabled_groups = self.config.get("enabled_groups", [])
        logger.info(f"修仙插件加载成功，生效群聊: {'所有群聊' if not self.enabled_groups else self.enabled_groups}")

    def _is_group_enabled(self, event: AstrMessageEvent) -> bool:
        # 尝试获取群号
        group_id = event.get_group_id()
        # 如果获取不到群号 (即 group_id 为 None)，说明是私聊
        if not group_id:
            return False

        # 如果插件没有配置生效群聊列表，则默认对所有群聊生效
        if not self.enabled_groups:
            print(self.enabled_groups)
            return True

        # 如果当前群号在生效列表里，则允许通过
        if str(group_id) in self.enabled_groups:
            return True

        # 其他情况（即在群聊中，但该群未被启用），则阻止
        return False

    def _get_db_connection(self):
        try:
            conn = sqlite3.connect(self.db_file, check_same_thread=False)
            conn.row_factory = self._dict_factory
            return conn
        except sqlite3.Error as e:
            logger.error(f"数据库连接失败: {e}")
            return None

    def _dict_factory(self, cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d

    def _init_database(self):
        self.data_path.mkdir(exist_ok=True)
        conn = self._get_db_connection()
        if not conn: return
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(players)")
        columns = [col['name'] for col in cursor.fetchall()]
        if 'level' in columns:
            logger.info("检测到旧版玩家表，正在升级...")
            cursor.execute("ALTER TABLE players RENAME TO players_old")
            cursor.execute(
                '''CREATE TABLE players (user_id TEXT PRIMARY KEY, nickname TEXT, major_level INTEGER DEFAULT 0, minor_level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0, gold INTEGER DEFAULT 0, spirit_root TEXT, is_seclusion BOOLEAN DEFAULT 0, seclusion_start_time REAL DEFAULT 0, hp INTEGER DEFAULT 100, max_hp INTEGER DEFAULT 100, attack INTEGER DEFAULT 10, defense INTEGER DEFAULT 5, sect_id INTEGER, sect_role TEXT, equipment TEXT, skills TEXT, last_checkin_date TEXT, created_at TEXT)''')
            cursor.execute(
                "INSERT INTO players (user_id, nickname, major_level, exp, gold, spirit_root, is_seclusion, seclusion_start_time, hp, max_hp, attack, defense, sect_id, sect_role, equipment, skills, last_checkin_date, created_at) SELECT user_id, nickname, level, exp, gold, spirit_root, is_seclusion, seclusion_start_time, hp, max_hp, attack, defense, sect_id, sect_role, equipment, skills, last_checkin_date, created_at FROM players_old")
            cursor.execute("DROP TABLE players_old")
            logger.info("玩家表结构升级完成。")
        else:
            cursor.execute(
                '''CREATE TABLE IF NOT EXISTS players (user_id TEXT PRIMARY KEY, nickname TEXT, major_level INTEGER DEFAULT 0, minor_level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0, gold INTEGER DEFAULT 0, spirit_root TEXT, is_seclusion BOOLEAN DEFAULT 0, seclusion_start_time REAL DEFAULT 0, hp INTEGER DEFAULT 100, max_hp INTEGER DEFAULT 100, attack INTEGER DEFAULT 10, defense INTEGER DEFAULT 5, sect_id INTEGER, sect_role TEXT, equipment TEXT, skills TEXT, last_checkin_date TEXT, created_at TEXT)''')

        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS items (item_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, type TEXT, description TEXT, price INTEGER, data TEXT)''')
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, item_id INTEGER, quantity INTEGER, is_equipped BOOLEAN DEFAULT 0, FOREIGN KEY (user_id) REFERENCES players (user_id), FOREIGN KEY (item_id) REFERENCES items (item_id))''')
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS sects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, leader_id TEXT, announcement TEXT, level INTEGER DEFAULT 1, resources INTEGER DEFAULT 0, created_at TEXT)''')

        # --- 新增逻辑 ---
        # 创建重置日志表，用于记录每日重置次数
        cursor.execute('''CREATE TABLE IF NOT EXISTS reset_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, reset_date TEXT)''')
        # --- 逻辑结束 ---

        self._populate_initial_items(cursor)
        conn.commit()
        conn.close()
        logger.info("数据库初始化检查完成。")

    def _populate_initial_items(self, cursor):
        cursor.execute("SELECT COUNT(*) FROM items")
        if cursor.fetchone()['COUNT(*)'] > 10:
            return

        cursor.execute("DELETE FROM items")

        elixirs = [
            ('引气丹', 'elixir', '炼气期基础丹药，恢复100点修为。', 50, json.dumps({'effect': 'add_exp', 'value': 100})),
            ('凝血草', 'elixir', '凡人草药，恢复20点气血。', 20, json.dumps({'effect': 'add_hp', 'value': 20})),
            ('小还丹', 'elixir', '江湖灵药，恢复100点气血。', 100, json.dumps({'effect': 'add_hp', 'value': 100})),
            ('大还丹', 'elixir', '强力疗伤药，恢复500点气血。', 450, json.dumps({'effect': 'add_hp', 'value': 500})),
            ('生生造化丹', 'elixir', '仙家神药，瞬间恢复全部气血。', 5000,
             json.dumps({'effect': 'add_hp', 'value': 999999})),
            ('聚气散', 'elixir', '使用后立即获得500点修为。', 200, json.dumps({'effect': 'add_exp', 'value': 500})),
            ('黄龙丹', 'elixir', '筑基期丹药，使用后立即获得2500点修为。', 800,
             json.dumps({'effect': 'add_exp', 'value': 2500})),
            ('玄天丹', 'elixir', '结丹期丹药，使用后立即获得12000点修为。', 3000,
             json.dumps({'effect': 'add_exp', 'value': 12000})),
            ('紫金丹', 'elixir', '元婴期丹药，使用后立即获得60000点修为。', 10000,
             json.dumps({'effect': 'add_exp', 'value': 60000})),
            ('筑基丹', 'elixir', '突破至筑基境时自动使用，成功率+20%。', 800,
             json.dumps({'effect': 'breakthrough_rate', 'value': 0.20, 'target_major_level': 0})),
            ('结金丹', 'elixir', '突破至结丹境时自动使用，成功率+15%。', 4000,
             json.dumps({'effect': 'breakthrough_rate', 'value': 0.15, 'target_major_level': 1})),
            ('破婴丹', 'elixir', '突破至元婴境时自动使用，成功率+10%。', 15000,
             json.dumps({'effect': 'breakthrough_rate', 'value': 0.10, 'target_major_level': 2})),
            ('化神丹', 'elixir', '突破至化神境时自动使用，成功率+5%。', 50000,
             json.dumps({'effect': 'breakthrough_rate', 'value': 0.05, 'target_major_level': 3})),
            ('清心丹', 'elixir', '突破时服用可静心凝神，略微增加成功率。', 1000,
             json.dumps({'effect': 'breakthrough_rate', 'value': 0.02, 'target_major_level': -1})),
            ('大力丸', 'elixir', '战斗中使用，10回合内攻击力提升20点。', 300,
             json.dumps({'effect': 'temp_buff', 'stat': 'attack', 'value': 20, 'duration': 10})),
            ('铁皮散', 'elixir', '战斗中使用，10回合内防御力提升15点。', 300,
             json.dumps({'effect': 'temp_buff', 'stat': 'defense', 'value': 15, 'duration': 10})),
            ('神行符', 'elixir', '战斗中使用，提升闪避率。', 500,
             json.dumps({'effect': 'temp_buff', 'stat': 'dodge', 'value': 0.1, 'duration': 5})),
            ('龙力丹', 'elixir', '极其稀有，永久增加10点攻击力。', 20000,
             json.dumps({'effect': 'permanent_stat', 'stat': 'attack', 'value': 10})),
            ('玄武丹', 'elixir', '极其稀有，永久增加8点防御力。', 20000,
             json.dumps({'effect': 'permanent_stat', 'stat': 'defense', 'value': 8})),
            ('朱果', 'elixir', '天地灵果，永久增加100点最大气血。', 15000,
             json.dumps({'effect': 'permanent_stat', 'stat': 'max_hp', 'value': 100})),
            ('洗髓丹', 'elixir', '有几率提升灵根品级，或变为更差。', 100000,
             json.dumps({'effect': 'reroll_spirit_root'})),
            ('忘尘丹', 'elixir', '忘记一门已学会的功法，返还部分灵石。', 1000, json.dumps({'effect': 'forget_skill'})),
            ('易名丹', 'elixir', '可以修改一次你的道号。', 5000, json.dumps({'effect': 'change_name'})),
            ('储物袋', 'elixir', '增加储物戒容量（功能待实现）。', 1000, json.dumps({'effect': 'expand_inventory'})),
            ('寻宝符', 'elixir', '外出历练时有更高几率遇到奇遇。', 800, json.dumps({'effect': 'increase_luck'})),
            ('养魂丹', 'elixir', '元婴期修士专用，缓慢恢复元神之力。', 2000,
             json.dumps({'effect': 'add_exp', 'value': 100, 'target_major_level': 3})),
            ('补天丹', 'elixir', '传说中的丹药，可弥补道基缺憾。', 99999, json.dumps({'effect': 'fix_foundation'})),
            ('九转还魂丹', 'elixir', '死亡时自动使用，免除一次死亡惩罚。', 50000,
             json.dumps({'effect': 'death_immunity'})),
            ('菩提子', 'elixir', '使用后进入顿悟状态，闭关收益翻倍，持续1小时。', 10000,
             json.dumps({'effect': 'exp_buff', 'multiplier': 2, 'duration_hour': 1})),
            ('魔心丹', 'elixir', '风险丹药，大幅提升修为，但可能走火入魔。', 5000,
             json.dumps({'effect': 'risky_exp', 'value': 50000})),
            ('龟息丹', 'elixir', '服用后进入假死状态，可避开强敌追杀。', 1500, json.dumps({'effect': 'escape'})),
            ('驻颜丹', 'elixir', '永葆青春，容颜不老。', 9999, json.dumps({'effect': 'cosmetic'}))]
        skills = [('长春功', 'skill_book', '【被动】基础吐纳法门，修炼速度提升5%。', 500,
                   json.dumps({'skill_name': '长春功', 'type': 'passive', 'effect': 'exp_rate', 'value': 0.05})),
                  ('铁布衫', 'skill_book', '【被动】凡人武学，永久增加10点防御和50点气血。', 600, json.dumps(
                      {'skill_name': '铁布衫', 'type': 'passive', 'effect': 'add_flat_stat',
                       'value': {'defense': 10, 'max_hp': 50}})),
                  ('基础剑诀', 'skill_book', '【被动】增加15点攻击力。', 600, json.dumps(
                      {'skill_name': '基础剑诀', 'type': 'passive', 'effect': 'add_flat_stat',
                       'value': {'attack': 15}})), ('御风术', 'skill_book', '【主动】战斗中提升自身速度，抢占先机。', 800,
                                                    json.dumps({'skill_name': '御风术', 'type': 'active',
                                                                'effect': 'self_buff', 'stat': 'speed', 'value': 20})),
                  ('火球术', 'skill_book', '【主动】发出一个火球，造成少量火属性伤害。', 800, json.dumps(
                      {'skill_name': '火球术', 'type': 'active', 'effect': 'damage', 'damage_type': 'fire',
                       'multiplier': 1.2})), ('混元功', 'skill_book', '【被动】筑基期心法，修炼速度提升12%。', 2500,
                                              json.dumps(
                                                  {'skill_name': '混元功', 'type': 'passive', 'effect': 'exp_rate',
                                                   'value': 0.12})),
                  ('金刚诀', 'skill_book', '【被动】防御力永久提升10%。', 3000, json.dumps(
                      {'skill_name': '金刚诀', 'type': 'passive', 'effect': 'add_percent_stat',
                       'value': {'defense': 0.10}})), ('青元剑诀', 'skill_book', '【被动】攻击力永久提升10%。', 3000,
                                                       json.dumps({'skill_name': '青元剑诀', 'type': 'passive',
                                                                   'effect': 'add_percent_stat',
                                                                   'value': {'attack': 0.10}})),
                  ('血燃术', 'skill_book', '【主动】燃烧气血，下一次攻击造成巨额伤害。', 5000, json.dumps(
                      {'skill_name': '血燃术', 'type': 'active', 'effect': 'sacrifice_buff', 'cost_hp_percent': 0.2,
                       'buff_multiplier': 2.5})), ('土牢术', 'skill_book', '【主动】困住敌人，使其一回合无法行动。', 4000,
                                                   json.dumps(
                                                       {'skill_name': '土牢术', 'type': 'active', 'effect': 'control',
                                                        'stun_rounds': 1})),
                  ('大衍诀', 'skill_book', '【被动】神识功法，修炼速度提升20%。', 8000,
                   json.dumps({'skill_name': '大衍诀', 'type': 'passive', 'effect': 'exp_rate', 'value': 0.20})),
                  ('万剑归宗', 'skill_book', '【主动】对敌方造成毁灭性的多段金属型伤害。', 15000, json.dumps(
                      {'skill_name': '万剑归宗', 'type': 'active', 'effect': 'multi_hit_damage', 'hits': 5,
                       'multiplier': 0.5})), ('春风化雨', 'skill_book', '【主动】持续恢复自身气血，持续3回合。', 12000,
                                              json.dumps({'skill_name': '春风化雨', 'type': 'active',
                                                          'effect': 'heal_over_time', 'percent': 0.1, 'duration': 3})),
                  ('不动明王身', 'skill_book', '【主动】进入绝对防御状态，免疫所有伤害，持续1回合。', 20000,
                   json.dumps({'skill_name': '不动明王身', 'type': 'active', 'effect': 'invincible', 'duration': 1})),
                  ('神行百变', 'skill_book', '【被动】身法秘籍，永久提升闪避率5%。', 9000, json.dumps(
                      {'skill_name': '神行百变', 'type': 'passive', 'effect': 'add_flat_stat',
                       'value': {'dodge': 0.05}})),
                  ('忘情天书', 'skill_book', '【被动】元婴期顶级心法，修炼速度提升30%。', 25000,
                   json.dumps({'skill_name': '忘情天书', 'type': 'passive', 'effect': 'exp_rate', 'value': 0.30})),
                  ('元磁神光', 'skill_book', '【主动】强大的神识攻击，无视部分防御。', 30000, json.dumps(
                      {'skill_name': '元磁神光', 'type': 'active', 'effect': 'true_damage', 'multiplier': 1.5,
                       'armor_pen': 0.3})),
                  ('法天象地', 'skill_book', '【主动】变身为巨人，全属性提升50%，持续3回合。', 50000, json.dumps(
                      {'skill_name': '法天象地', 'type': 'active', 'effect': 'self_buff_percent', 'value': 0.5,
                       'duration': 3})),
                  ('一气化三清', 'skill_book', '【主动】召唤两个分身协同作战，分身拥有本体30%实力。', 60000, json.dumps(
                      {'skill_name': '一气化三清', 'type': 'active', 'effect': 'summon', 'count': 2, 'strength': 0.3})),
                  ('涅槃真经', 'skill_book', '【被动】气血低于10%时，有几率瞬间恢复50%气血，每场战斗限一次。', 40000,
                   json.dumps({'skill_name': '涅槃真经', 'type': 'passive', 'effect': 'second_wind', 'trigger_hp': 0.1,
                               'heal_percent': 0.5})),
                  ('太上感应篇', 'skill_book', '【被动】化神期心法，修炼速度提升50%。', 100000,
                   json.dumps({'skill_name': '太上感应篇', 'type': 'passive', 'effect': 'exp_rate', 'value': 0.50})),
                  ('言出法随', 'skill_book', '【主动】口含天宪，有小几率直接判定敌人败北。', 999999,
                   json.dumps({'skill_name': '言出法随', 'type': 'active', 'effect': 'instant_win', 'chance': 0.001})),
                  ('掌中佛国', 'skill_book', '【主动】将敌人收入掌中世界，造成巨大空间伤害。', 250000, json.dumps(
                      {'skill_name': '掌中佛国', 'type': 'active', 'effect': 'damage', 'damage_type': 'space',
                       'multiplier': 5.0})), ('时间静止', 'skill_book', '【主动】暂停时间，连续行动3回合。', 500000,
                                              json.dumps(
                                                  {'skill_name': '时间静止', 'type': 'active', 'effect': 'extra_turn',
                                                   'turns': 3})),
                  ('命运轮盘', 'skill_book', '【主动】随机触发一种强大的正面或负面效果。', 88888,
                   json.dumps({'skill_name': '命运轮盘', 'type': 'active', 'effect': 'random'})),
                  ('他化自在法', 'skill_book', '【主动】短暂复制对手的一项功法为己用。', 180000,
                   json.dumps({'skill_name': '他化自在法', 'type': 'active', 'effect': 'copy_skill'})),
                  ('因果之道', 'skill_book', '【被动】受到的部分伤害将返还给攻击者。', 150000,
                   json.dumps({'skill_name': '因果之道', 'type': 'passive', 'effect': 'thorns', 'percent': 0.15})),
                  ('轮回之眼', 'skill_book', '【被动】看破一切虚妄，大幅降低被控制的几率。', 120000, json.dumps(
                      {'skill_name': '轮回之眼', 'type': 'passive', 'effect': 'control_resistance', 'value': 0.5})),
                  ('斩三尸证道诀', 'skill_book', '【被动】大乘境无上法门，全属性永久提升20%。', 800000, json.dumps(
                      {'skill_name': '斩三尸证道诀', 'type': 'passive', 'effect': 'add_percent_stat',
                       'value': {'attack': 0.2, 'defense': 0.2, 'max_hp': 0.2}})),
                  ('大道无形', 'skill_book', '【被动】与天地同寿，与日月同辉。', 9999999,
                   json.dumps({'skill_name': '大道无形', 'type': 'passive', 'effect': 'god_mode'})),
                  ('点石成金', 'skill_book', '【主动】消耗大量修为，随机获得灵石。', 10000,
                   json.dumps({'skill_name': '点石成金', 'type': 'active', 'effect': 'create_gold'}))]
        all_items = elixirs + skills
        cursor.executemany("INSERT INTO items (name, type, description, price, data) VALUES (?, ?, ?, ?, ?)", all_items)
        logger.info(f"数据库已填充 {len(all_items)} 种初始物品。")

    def _get_player(self, user_id: str, calculate_exp: bool = True):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        player = cursor.fetchone()
        conn.close()
        if not player: return None
        if calculate_exp and player["is_seclusion"]:
            now = time.time()
            duration_minutes = (now - player["seclusion_start_time"]) / 60
            if duration_minutes > 0:
                skills = json.loads(player.get("skills") or "{}")
                exp_rate_bonus = 1.0
                for skill_data in skills.values():
                    if skill_data.get('type') == 'passive' and skill_data.get("effect") == "exp_rate":
                        exp_rate_bonus += skill_data.get("value", 0)
                root_rate = self.SPIRIT_ROOTS[player["spirit_root"]]["rate"]
                added_exp = int(duration_minutes * self.EXP_PER_MINUTE * root_rate * exp_rate_bonus)
                player["exp"] += added_exp
                player["seclusion_start_time"] = now
                self._update_player(user_id, {"exp": player["exp"], "seclusion_start_time": now})
        return player

    def _update_player(self, user_id: str, data: dict):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        updates = ", ".join([f"{key} = ?" for key in data.keys()])
        values = list(data.values())
        values.append(user_id)
        cursor.execute(f"UPDATE players SET {updates} WHERE user_id = ?", tuple(values))
        conn.commit()
        conn.close()

    def _get_realm_info(self, major_level: int, minor_level: int):
        if major_level >= len(self.REALM_CONFIG):
            major_level = len(self.REALM_CONFIG) - 1
        realm = self.REALM_CONFIG[major_level]
        name = realm['name']
        display = realm['display'](minor_level)
        max_minor = realm['levels']
        exp_base = realm['exp_base']
        exp_needed = int(exp_base * (minor_level ** 1.5) * (major_level * 1.2 + 1))
        return {"full_name": f"{name}·{display}", "major_name": name, "minor_name": display, "major_level": major_level,
                "minor_level": minor_level, "max_minor_level": max_minor, "exp_needed": exp_needed}

    def _recalculate_stats(self, user_id: str):
        player = self._get_player(user_id, calculate_exp=False)
        if not player: return
        major_level, minor_level = player['major_level'], player['minor_level']
        base_attack = 10 + major_level * 10 + minor_level * 2
        base_defense = 5 + major_level * 8 + minor_level
        base_max_hp = 100 + major_level * 100 + minor_level * 10
        eq_attack, eq_defense, eq_max_hp = 0, 0, 0
        equipment = json.loads(player.get("equipment") or "{}")
        if equipment:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            item_ids = tuple(equipment.values())
            if item_ids:
                cursor.execute(f"SELECT data FROM items WHERE item_id IN ({','.join('?' for _ in item_ids)})", item_ids)
                items = cursor.fetchall()
                for item in items:
                    item_data = json.loads(item['data'])
                    eq_attack += item_data.get('attack', 0)
                    eq_defense += item_data.get('defense', 0)
                    eq_max_hp += item_data.get('hp', 0)
            conn.close()
        skill_add_stats = {'attack': 0, 'defense': 0, 'max_hp': 0}
        skill_percent_stats = {'attack': 1.0, 'defense': 1.0, 'max_hp': 1.0}
        skills = json.loads(player.get("skills") or "{}")
        for skill_data in skills.values():
            if skill_data.get('type') == 'passive':
                if skill_data.get('effect') == 'add_flat_stat':
                    for stat, value in skill_data['value'].items():
                        skill_add_stats[stat] = skill_add_stats.get(stat, 0) + value
                elif skill_data.get('effect') == 'add_percent_stat':
                    for stat, value in skill_data['value'].items():
                        skill_percent_stats[stat] = skill_percent_stats.get(stat, 1.0) + value
        total_attack = int((base_attack + eq_attack + skill_add_stats['attack']) * skill_percent_stats['attack'])
        total_defense = int((base_defense + eq_defense + skill_add_stats['defense']) * skill_percent_stats['defense'])
        total_max_hp = int((base_max_hp + eq_max_hp + skill_add_stats['max_hp']) * skill_percent_stats['max_hp'])
        new_stats = {"attack": total_attack, "defense": total_defense, "max_hp": total_max_hp,
                     "hp": min(player['hp'], total_max_hp)}
        self._update_player(user_id, new_stats)

    def _remove_item_from_inventory(self, user_id: str, item_id: int, quantity: int = 1):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, quantity FROM inventory WHERE user_id = ? AND item_id = ?", (user_id, item_id))
        item = cursor.fetchone()
        if not item or item['quantity'] < quantity:
            conn.close()
            return False
        if item['quantity'] > quantity:
            cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (item['quantity'] - quantity, item['id']))
        else:
            cursor.execute("DELETE FROM inventory WHERE id = ?", (item['id'],))
        conn.commit()
        conn.close()
        return True

    async def terminate(self):
        logger.info("修仙插件已卸载。")

    @filter.command("我要修仙")
    async def start_xiuxian(self, event: AstrMessageEvent):
        '''踏上仙途，开启你的传说。'''
        if not self._is_group_enabled(event):
            event.stop_event()
            return
        user_id = event.get_sender_id()
        if self._get_player(user_id, calculate_exp=False):
            yield event.plain_result("道友已经踏入仙途，无需重复入门。")
            event.stop_event()
            return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        root_type = random.choice(list(self.SPIRIT_ROOTS.keys()))
        cursor.execute(
            "INSERT INTO players (user_id, nickname, gold, spirit_root, equipment, skills, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, event.get_sender_name(), self.INITIAL_GOLD, root_type, '{}', '{}',
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        self._recalculate_stats(user_id)
        root_info = self.SPIRIT_ROOTS[root_type]
        realm_info = self._get_realm_info(0, 1)
        msg = (
            f"仙路尽头谁为峰，一见道友皆成空！\n恭喜 {event.get_sender_name()} 踏入仙途！\n你的灵根是【{root_type}灵根】，{root_info['desc']}。\n获赠启动灵石：{self.INITIAL_GOLD}枚。\n当前境界：{realm_info['full_name']}\n发送 /修仙面板 查看状态，发送 /闭关 开始获取修为吧！")
        yield event.plain_result(msg)
        event.stop_event()

    @filter.command("修仙面板")
    async def show_status(self, event: AstrMessageEvent):
        '''查看你当前的详细修仙状态。'''
        if not self._is_group_enabled(event):
            event.stop_event()
            return
        user_id = event.get_sender_id()
        player = self._get_player(user_id)
        if not player:
            yield event.plain_result("你尚未踏入仙途，请发送 /我要修仙 开始。")
            event.stop_event()
            return
        realm_info = self._get_realm_info(player['major_level'], player['minor_level'])
        exp_to_next_level = realm_info['exp_needed']
        sect_name = "无"
        if player['sect_id']:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sects WHERE id = ?", (player['sect_id'],))
            sect = cursor.fetchone()
            conn.close()
            if sect:
                sect_name = sect['name']
        status_msg = (f"--- 道友 {player['nickname']} 的信息 ---\n"
                      f"灵根: 【{player['spirit_root']}灵根】\n"
                      f"境界: {realm_info['full_name']}\n"
                      f"修为: {player['exp']} / {exp_to_next_level}\n"
                      f"灵石: {player['gold']}\n"
                      f"宗门: {sect_name} ({player.get('sect_role', '无')})\n"
                      f"气血: {player['hp']} / {player['max_hp']}\n"
                      f"攻击: {player['attack']}\n"
                      f"防御: {player['defense']}\n"
                      f"状态: {'闭关中...' if player['is_seclusion'] else '修炼中'}\n"
                      f"仙途始于: {player['created_at']}")
        yield event.plain_result(status_msg)
        event.stop_event()

    @filter.command("闭关")
    async def start_seclusion(self, event: AstrMessageEvent):
        '''进入闭关状态，持续获得修为。'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player = self._get_player(user_id, calculate_exp=False)
        if not player:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        if player["is_seclusion"]:
            yield event.plain_result("你正在闭关中，请勿打扰。")
            event.stop_event()
            return
        self._update_player(user_id, {"is_seclusion": 1, "seclusion_start_time": time.time()})
        yield event.plain_result("你已进入闭关状态，灵气正源源不断地汇入你的体内...\n(发送 /出关 来查看成果)")
        event.stop_event()

    @filter.command("出关")
    async def end_seclusion(self, event: AstrMessageEvent):
        '''结束闭关，结算本次修炼所得。'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player = self._get_player(user_id, calculate_exp=False)
        if not player:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        if not player["is_seclusion"]:
            yield event.plain_result("你并未在闭关状态。")
            event.stop_event()
            return
        start_time = player["seclusion_start_time"]
        current_exp = player["exp"]
        updated_player = self._get_player(user_id, calculate_exp=True)
        added_exp = updated_player['exp'] - current_exp
        self._update_player(user_id, {"is_seclusion": 0})
        duration_seconds = time.time() - start_time
        hours, rem = divmod(duration_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        duration_str = f"{int(hours)}小时 {int(minutes)}分钟 {int(seconds)}秒"
        msg = (f"闭关结束！\n本次闭关时长：{duration_str}\n共获得修为：{added_exp}\n当前总修为：{updated_player['exp']}\n")
        yield event.plain_result(msg)
        event.stop_event()

    @filter.command("突破")
    async def breakthrough(self, event: AstrMessageEvent):
        '''消耗修为，尝试冲击下一境界。'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player = self._get_player(user_id)
        if not player:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        if player["is_seclusion"]:
            yield event.plain_result("闭关期间心神不宁，无法突破，请先 /出关。")
            event.stop_event()
            return
        major_level, minor_level = player['major_level'], player['minor_level']
        realm_info = self._get_realm_info(major_level, minor_level)
        if realm_info['major_name'] == "真仙":
            yield event.plain_result("恭喜道友！你已是此界之巅，无需再突破了！")
            event.stop_event()
            return
        exp_needed = realm_info['exp_needed']
        if player["exp"] < exp_needed:
            yield event.plain_result(f"修为不足，无法突破！\n当前修为：{player['exp']}\n需要修为：{exp_needed}")
            event.stop_event()
            return
        success_rate = 0.8 - major_level * 0.05 - minor_level * 0.01
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT T1.item_id, T2.data, T2.name FROM inventory AS T1 JOIN items AS T2 ON T1.item_id = T2.item_id WHERE T1.user_id = ? AND T2.type = 'elixir'",
            (user_id,))
        elixirs = cursor.fetchall()
        conn.close()
        elixir_bonus = 0
        elixir_used_msg = ""
        for elixir in elixirs:
            data = json.loads(elixir['data'])
            if data.get('effect') == 'breakthrough_rate' and (
                    data.get('target_major_level') == major_level or data.get('target_major_level') == -1):
                elixir_bonus += data.get('value', 0)
                self._remove_item_from_inventory(user_id, elixir['item_id'])
                elixir_used_msg = f"\n你服下了【{elixir['name']}】，感觉突破的把握更大了！(成功率+{elixir_bonus * 100:.1f}%)"
                break
        success_rate = min(0.95, success_rate + elixir_bonus)
        new_exp = player["exp"] - exp_needed
        if random.random() < success_rate:
            new_major, new_minor = major_level, minor_level + 1
            if new_minor > realm_info['max_minor_level']:
                new_major += 1
                new_minor = 1
            self._update_player(user_id, {"major_level": new_major, "minor_level": new_minor, "exp": new_exp})
            self._recalculate_stats(user_id)
            new_realm_info = self._get_realm_info(new_major, new_minor)
            msg = (f"天降祥瑞，恭喜道友成功突破到了【{new_realm_info['full_name']}】！{elixir_used_msg}")
        else:
            new_exp = max(0, new_exp - int(exp_needed * 0.2))
            self._update_player(user_id, {"exp": new_exp})
            msg = (f"突破失败！你被心魔所噬，气息紊乱，修为略有倒退。{elixir_used_msg}")
        yield event.plain_result(msg)
        event.stop_event()

    @filter.command("修仙签到")
    async def daily_checkin(self, event: AstrMessageEvent):
        '''每日签到可领取奖励。'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player = self._get_player(user_id)
        if not player:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        today = datetime.now().strftime("%Y-%m-%d")
        if player.get('last_checkin_date') == today:
            yield event.plain_result("道友今日已签到，请明日再来。")
            event.stop_event()
            return
        gold_reward = random.randint(50, 150) + player['major_level'] * 20
        exp_reward = random.randint(100, 300) + player['major_level'] * 50
        new_gold = player['gold'] + gold_reward
        new_exp = player['exp'] + exp_reward
        self._update_player(user_id, {"gold": new_gold, "exp": new_exp, "last_checkin_date": today})
        yield event.plain_result(f"签到成功！\n你获得了 {gold_reward} 灵石和 {exp_reward} 修为。")
        event.stop_event()

    @filter.command("使用")
    async def use_item(self, event: AstrMessageEvent):
        '''使用储物戒中的消耗品。用法: /使用 [物品名称]'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player = self._get_player(user_id)
        if not player:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        item_name = event.message_str.strip()
        if not item_name:
            yield event.plain_result("请指定要使用的物品。用法: /使用 [物品名称]")
            event.stop_event()
            return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT T1.item_id, T2.data, T2.type FROM inventory AS T1 JOIN items AS T2 ON T1.item_id = T2.item_id WHERE T1.user_id = ? AND T2.name = ?",
            (user_id, item_name))
        item_to_use = cursor.fetchone()
        conn.close()
        if not item_to_use:
            yield event.plain_result(f"你的储物戒里没有【{item_name}】。")
            event.stop_event()
            return
        if item_to_use['type'] == 'skill_book':
            yield event.plain_result(
            f"【{item_name}】是功法秘籍，请使用 /学习 指令。")
            event.stop_event()
            return
        item_id = item_to_use['item_id']
        data = json.loads(item_to_use['data'])
        effect = data.get('effect')
        if not self._remove_item_from_inventory(user_id, item_id):
            yield event.plain_result("物品移除失败，请联系管理员。")
            event.stop_event()
            return
        if effect == 'add_exp':
            value = data.get('value', 0)
            self._update_player(user_id, {"exp": player['exp'] + value})
            yield event.plain_result(f"你使用了【{item_name}】，一股暖流涌入丹田，修为了提升了 {value} 点！")
        elif effect == 'add_hp':
            value = data.get('value', 0)
            new_hp = min(player['max_hp'], player['hp'] + value)
            self._update_player(user_id, {"hp": new_hp})
            yield event.plain_result(f"你服下了【{item_name}】，伤势恢复了 {value} 点气血！")
        elif effect == 'permanent_stat':
            stat = data.get('stat')
            value = data.get('value')
            self._update_player(user_id, {stat: player[stat] + value})
            self._recalculate_stats(user_id)
            yield event.plain_result(f"你炼化了【{item_name}】，感觉根基更加稳固，{stat}永久提升了{value}点！")
        else:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?",
                           (user_id, item_id))
            conn.commit()
            conn.close()
            yield event.plain_result(f"【{item_name}】似乎不能这样使用。")
        event.stop_event()

    @filter.command("学习")
    async def learn_skill(self, event: AstrMessageEvent):
        '''学习功法秘籍。用法: /学习 [功法名称]'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player = self._get_player(user_id)
        if not player:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        skill_book_name = event.message_str.strip()
        if not skill_book_name:
            yield event.plain_result("请指定要学习的功法。用法: /学习 [功法名称]")
            event.stop_event()
            return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT T1.item_id, T2.data FROM inventory AS T1 JOIN items AS T2 ON T1.item_id = T2.item_id WHERE T1.user_id = ? AND T2.name = ? AND T2.type = 'skill_book'",
            (user_id, skill_book_name))
        book_to_learn = cursor.fetchone()
        conn.close()
        if not book_to_learn:
            yield event.plain_result(f"你的储物戒里没有【{skill_book_name}】这本秘籍。")
            event.stop_event()
            return
        book_id = book_to_learn['item_id']
        book_data = json.loads(book_to_learn['data'])
        skill_name = book_data.get('skill_name')
        skills = json.loads(player.get('skills') or '{}')
        if skill_name in skills:
            yield event.plain_result(f"你已经掌握了【{skill_name}】，无需重复学习。");
            event.stop_event()
            return
        if self._remove_item_from_inventory(user_id, book_id):
            skills[skill_name] = book_data
            self._update_player(user_id, {"skills": json.dumps(skills)})
            self._recalculate_stats(user_id)  # 学习被动功法后更新属性
            yield event.plain_result(f"你潜心研读【{skill_book_name}】，成功领悟了【{skill_name}】！")
        else:
            yield event.plain_result("学习失败，请联系管理员。")
        event.stop_event()

    @filter.command("修仙排行", "排行")
    async def show_ranking(self, event: AstrMessageEvent, rank_type: str = "境界"):
        '''查看服务器排行榜。用法: /修仙排行 [修为/境界/财富]'''
        if not self._is_group_enabled(event): return

        conn = self._get_db_connection()
        cursor = conn.cursor()

        if "修为" in rank_type:
            title = "--- 修为排行榜 ---"
            cursor.execute("SELECT nickname, exp FROM players ORDER BY exp DESC LIMIT 10")
            players = cursor.fetchall()
            msg = f"{title}\n"
            for i, p in enumerate(players):
                msg += f"第{i + 1}名: {p['nickname']} - {p['exp']} 点修为\n"
        elif "境界" in rank_type:
            title = "--- 境界排行榜 ---"
            cursor.execute(
                "SELECT nickname, major_level, minor_level FROM players ORDER BY major_level DESC, minor_level DESC, exp DESC LIMIT 10")
            players = cursor.fetchall()
            msg = f"{title}\n"
            for i, p in enumerate(players):
                realm_info = self._get_realm_info(p['major_level'], p['minor_level'])
                msg += f"第{i + 1}名: {p['nickname']} - {realm_info['full_name']}\n"
        elif "财富" in rank_type:
            title = "--- 财富排行榜 ---"
            cursor.execute("SELECT nickname, gold FROM players ORDER BY gold DESC LIMIT 10")
            players = cursor.fetchall()
            msg = f"{title}\n"
            for i, p in enumerate(players):
                msg += f"第{i + 1}名: {p['nickname']} - {p['gold']} 灵石\n"
        else:
            conn.close()
            yield event.plain_result("无效的排行榜类型。支持的类型: 修为, 境界, 财富");
            return

        conn.close()
        yield event.plain_result(msg)
        event.stop_event()

    @filter.command("切磋")
    async def player_vs_player(self, event: AstrMessageEvent):
        '''与其他道友切磋一番。用法: /切磋 @用户'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player1 = self._get_player(user_id)
        if not player1:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        target_id = event.get_at_user_id()
        if not target_id:
            yield event.plain_result("请@你要切磋的道友。")
            event.stop_event()
            return
        if target_id == user_id:
            yield event.plain_result("道友，不可与自己为敌。")
            event.stop_event()
            return
        player2 = self._get_player(target_id)
        if not player2:
            yield event.plain_result("对方尚未踏入仙途。")
            event.stop_event()
            return
        p1_hp, p2_hp = player1['hp'], player2['hp']
        p1_atk, p1_def = player1['attack'], player1['defense']
        p2_atk, p2_def = player2['attack'], player2['defense']
        battle_log = f"--- {player1['nickname']} vs {player2['nickname']} ---\n"
        turn = 0
        while p1_hp > 0 and p2_hp > 0:
            turn += 1
            if turn > 20: battle_log += "双方大战二十回合，未分胜负，遂罢手言和。\n"; break
            damage1 = max(1, p1_atk - p2_def + random.randint(-5, 5))
            p2_hp -= damage1
            battle_log += f"回合{turn}: {player1['nickname']}对{player2['nickname']}造成了{damage1}点伤害！({player2['nickname']}剩余{max(0, p2_hp)}气血)\n"
            if p2_hp <= 0: break
            damage2 = max(1, p2_atk - p1_def + random.randint(-5, 5))
            p1_hp -= damage2
            battle_log += f"回合{turn}: {player2['nickname']}对{player1['nickname']}造成了{damage2}点伤害！({player1['nickname']}剩余{max(0, p1_hp)}气血)\n"
        if p1_hp > p2_hp:
            winner, loser = player1, player2
        else:
            winner, loser = player2, player1
        reward = random.randint(10, 50)
        loser_gold_loss = min(loser['gold'], reward)
        self._update_player(winner['user_id'], {'gold': winner['gold'] + loser_gold_loss, 'hp': winner['max_hp']})
        self._update_player(loser['user_id'], {'gold': loser['gold'] - loser_gold_loss, 'hp': loser['max_hp']})
        battle_log += f"\n战斗结束！【{winner['nickname']}】技高一筹，战胜了【{loser['nickname']}】！\n并获得了{loser_gold_loss}灵石作为战利品。"
        yield event.plain_result(battle_log)
        event.stop_event()

    @filter.command("储物戒")
    async def show_inventory(self, event: AstrMessageEvent):
        '''查看你储物戒中的所有物品。'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        if not self._get_player(user_id):
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT T2.name, T1.quantity, T1.is_equipped FROM inventory AS T1 JOIN items AS T2 ON T1.item_id = T2.item_id WHERE T1.user_id = ?''',
            (user_id,))
        items = cursor.fetchall()
        conn.close()
        if not items:
            yield event.plain_result("你的储物戒空空如也，仿佛被洗劫过一番。")
            event.stop_event()
            return
        msg = "--- 我的储物戒 ---\n"
        for item in items:
            equipped_str = " (已装备)" if item['is_equipped'] else ""
            msg += f"【{item['name']}】x {item['quantity']}{equipped_str}\n"
        yield event.plain_result(msg)
        event.stop_event()

    @filter.command("装备")
    async def equip_item(self, event: AstrMessageEvent):
        '''装备储物戒中的一件物品。用法: /装备 [物品名称]'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player = self._get_player(user_id)
        if not player:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        item_name = event.message_str.strip()
        if not item_name:
            yield event.plain_result("请指定要装备的物品名称。用法: /装备 [物品名称]")
            event.stop_event()
            return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT item_id, type FROM items WHERE name = ?", (item_name,))
        item_to_equip = cursor.fetchone()
        if not item_to_equip:
            conn.close()
            yield event.plain_result(f"世间并无【{item_name}】此物。")
            event.stop_event()
            return
        cursor.execute("SELECT id FROM inventory WHERE user_id = ? AND item_id = ?",
                       (user_id, item_to_equip['item_id']))
        if not cursor.fetchone():
            conn.close()
            yield event.plain_result("你的储物戒里没有这件东西。")
            event.stop_event()
            return
        item_type = item_to_equip['type']
        if item_type not in self.EQUIPMENT_SLOTS:
            conn.close()
            yield event.plain_result(
            f"【{item_name}】不是一件可装备的物品。")
            event.stop_event()
            return
        equipment = json.loads(player.get("equipment") or "{}")
        if item_type in equipment:
            old_item_id = equipment[item_type]
            cursor.execute("UPDATE inventory SET is_equipped = 0 WHERE user_id = ? AND item_id = ?",
                           (user_id, old_item_id))
        equipment[item_type] = item_to_equip['item_id']
        cursor.execute("UPDATE inventory SET is_equipped = 1 WHERE user_id = ? AND item_id = ?",
                       (user_id, item_to_equip['item_id']))
        conn.commit()
        conn.close()
        self._update_player(user_id, {"equipment": json.dumps(equipment)})
        self._recalculate_stats(user_id)
        yield event.plain_result(f"你已成功装备【{item_name}】。")
        event.stop_event()

    @filter.command("坊市")
    async def show_shop(self, event: AstrMessageEvent):
        '''查看坊市中正在出售的商品。'''
        if not self._is_group_enabled(event): return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, description, price FROM items WHERE price > 0 ORDER BY price ASC")
        items = cursor.fetchall()
        conn.close()
        msg = "--- 欢迎光临天机阁坊市 ---\n"
        for item in items:
            msg += f"【{item['name']}】价格: {item['price']} 灵石\n  描述: {item['description']}\n"
        msg += "\n使用 /购买 [物品名称] 来购买。"
        yield event.plain_result(msg)
        event.stop_event()

    @filter.command("购买")
    async def buy_item(self, event: AstrMessageEvent):
        '''在坊市购买一件物品。用法: /购买 [物品名称]'''
        if not self._is_group_enabled(event): return
        user_id = event.get_sender_id()
        player = self._get_player(user_id)
        if not player:
            yield event.plain_result("你尚未踏入仙途。")
            event.stop_event()
            return
        item_name = event.message_str.strip()
        if not item_name:
            yield event.plain_result("道友想买些什么？用法: /购买 [物品名称]")
            event.stop_event()
            return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT item_id, price FROM items WHERE name = ?", (item_name,))
        item_to_buy = cursor.fetchone()
        if not item_to_buy or not item_to_buy['price']:
            conn.close()
            yield event.plain_result("坊市中没有此物出售。")
            event.stop_event()
            return
        if player["gold"] < item_to_buy["price"]:
            conn.close()
            yield event.plain_result(f"你的灵石不足！需要 {item_to_buy['price']}，你只有 {player['gold']}。")
            event.stop_event()
            return
        new_gold = player["gold"] - item_to_buy["price"]
        self._update_player(user_id, {"gold": new_gold})
        cursor.execute("SELECT id, quantity FROM inventory WHERE user_id = ? AND item_id = ?",
                       (user_id, item_to_buy['item_id']))
        existing_item = cursor.fetchone()
        if existing_item:
            cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?",
                           (existing_item['quantity'] + 1, existing_item['id']))
        else:
            cursor.execute("INSERT INTO inventory (user_id, item_id, quantity) VALUES (?, ?, ?)",
                           (user_id, item_to_buy['item_id'], 1))
        conn.commit()
        conn.close()
        yield event.plain_result(f"购买【{item_name}】成功！花费了 {item_to_buy['price']} 灵石。")
        event.stop_event()

    @filter.command("重置修仙数据")
    async def reset_data(self, event: AstrMessageEvent):
        '''【高危】删除你的所有修仙数据，重入轮回。每位玩家每日仅限一次。'''
        if not self._is_group_enabled(event): return

        user_id = event.get_sender_id()
        if not self._get_player(user_id, calculate_exp=False):
            yield event.plain_result("未找到你的修仙数据。")
            return

        today = datetime.now().strftime("%Y-%m-%d")
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM reset_logs WHERE user_id = ? AND reset_date = ?", (user_id, today))
        already_reset = cursor.fetchone()
        conn.close()

        if already_reset:
            yield event.plain_result("道友，天命不可常改，每日仅有一次重入轮回之机。请明日再来吧。")
            return

        confirm_key = f"xiuxian_reset_confirm_{user_id}"
        if self.context.get(confirm_key):
            # 再次确认可以重置
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM players WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM inventory WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM sects WHERE leader_id = ?", (user_id,))
            cursor.execute("INSERT INTO reset_logs (user_id, reset_date) VALUES (?, ?)", (user_id, today))

            conn.commit()
            conn.close()
            self.context.delete(confirm_key)
            yield event.plain_result("你的所有尘缘已了，重入轮回。")
        else:
            self.context.set(confirm_key, True, ttl=60)
            yield event.plain_result(
                "此操作将删除你的所有数据且无法恢复！\n若道心坚定，请在60秒内再次发送 /重置修仙数据 以确认。")
