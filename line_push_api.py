"""
LINE Messaging API - Push Message 実装
LINE Bot APIを使用してプッシュメッセージを送信するためのモジュール
"""

import requests
import json
from typing import List, Dict, Optional, Union
from enum import Enum


class MessageType(Enum):
    """メッセージタイプの列挙型"""
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    LOCATION = "location"
    STICKER = "sticker"
    IMAGEMAP = "imagemap"
    TEMPLATE = "template"
    FLEX = "flex"


class LinePushAPI:
    """LINE Push API クライアントクラス"""
    
    BASE_URL = "https://api.line.me/v2/bot"
    
    def __init__(self, channel_access_token: str):
        """
        初期化
        
        Args:
            channel_access_token: LINE Channel Access Token
        """
        self.channel_access_token = channel_access_token
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {channel_access_token}"
        }
    
    def _send_request(self, url: str, payload: Dict) -> Dict:
        """
        APIリクエストを送信
        
        Args:
            url: リクエストURL
            payload: リクエストペイロード
            
        Returns:
            APIレスポンス
            
        Raises:
            Exception: APIリクエストが失敗した場合
        """
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=1)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTPエラー: {e.response.status_code}"
            try:
                error_detail = e.response.json()
                error_msg += f" - {error_detail}"
            except:
                error_msg += f" - {e.response.text}"
            raise Exception(error_msg) from e
        except requests.exceptions.RequestException as e:
            raise Exception(f"リクエストエラー: {str(e)}") from e
    
    def push_message(
        self,
        user_id: str,
        messages: List[Dict],
        notification_disabled: bool = False
    ) -> Dict:
        """
        プッシュメッセージを送信
        
        Args:
            user_id: 送信先ユーザーID
            messages: メッセージオブジェクトのリスト
            notification_disabled: 通知を無効にするかどうか
            
        Returns:
            APIレスポンス
        """
        url = f"{self.BASE_URL}/message/push"
        payload = {
            "to": user_id,
            "messages": messages,
            "notificationDisabled": notification_disabled
        }
        return self._send_request(url, payload)
    
    @staticmethod
    def create_text_message(text: str, quick_reply: Optional[Dict] = None) -> Dict:
        """
        テキストメッセージを作成
        
        Args:
            text: メッセージテキスト（最大5000文字）
            quick_reply: クイックリプライオブジェクト（オプション）
            
        Returns:
            メッセージオブジェクト
        """
        message = {
            "type": MessageType.TEXT.value,
            "text": text
        }
        if quick_reply:
            message["quickReply"] = quick_reply
        return message
    
    @staticmethod
    def create_image_message(
        original_content_url: str,
        preview_image_url: Optional[str] = None
    ) -> Dict:
        """
        画像メッセージを作成
        
        Args:
            original_content_url: 画像URL（HTTPS、最大1000x1000px、JPEG/PNG、最大10MB）
            preview_image_url: プレビュー画像URL（オプション、最大240x240px）
            
        Returns:
            メッセージオブジェクト
        """
        message = {
            "type": MessageType.IMAGE.value,
            "originalContentUrl": original_content_url,
            "previewImageUrl": preview_image_url or original_content_url
        }
        return message
    
    @staticmethod
    def create_location_message(
        title: str,
        address: str,
        latitude: float,
        longitude: float
    ) -> Dict:
        """
        位置情報メッセージを作成
        
        Args:
            title: タイトル
            address: 住所
            latitude: 緯度
            longitude: 経度
            
        Returns:
            メッセージオブジェクト
        """
        return {
            "type": MessageType.LOCATION.value,
            "title": title,
            "address": address,
            "latitude": latitude,
            "longitude": longitude
        }
    
    @staticmethod
    def create_sticker_message(
        package_id: str,
        sticker_id: str
    ) -> Dict:
        """
        スタンプメッセージを作成
        
        Args:
            package_id: スタンプパッケージID
            sticker_id: スタンプID
            
        Returns:
            メッセージオブジェクト
        """
        return {
            "type": MessageType.STICKER.value,
            "packageId": package_id,
            "stickerId": sticker_id
        }
    
    @staticmethod
    def create_template_message(
        alt_text: str,
        template: Dict
    ) -> Dict:
        """
        テンプレートメッセージを作成
        
        Args:
            alt_text: 代替テキスト
            template: テンプレートオブジェクト
            
        Returns:
            メッセージオブジェクト
        """
        return {
            "type": MessageType.TEMPLATE.value,
            "altText": alt_text,
            "template": template
        }
    
    @staticmethod
    def create_buttons_template(
        thumbnail_image_url: Optional[str],
        title: str,
        text: str,
        actions: List[Dict],
        image_aspect_ratio: str = "rectangle",
        image_size: str = "cover",
        image_background_color: str = "#FFFFFF"
    ) -> Dict:
        """
        ボタンテンプレートを作成
        
        Args:
            thumbnail_image_url: サムネイル画像URL（オプション）
            title: タイトル（最大40文字）
            text: メッセージテキスト（最大160文字）
            actions: アクションのリスト（最大4個）
            image_aspect_ratio: 画像のアスペクト比（"rectangle" or "square"）
            image_size: 画像サイズ（"cover" or "contain"）
            image_background_color: 画像背景色（HEX形式）
            
        Returns:
            テンプレートオブジェクト
        """
        template = {
            "type": "buttons",
            "text": text,
            "actions": actions
        }
        if thumbnail_image_url:
            template["thumbnailImageUrl"] = thumbnail_image_url
            template["imageAspectRatio"] = image_aspect_ratio
            template["imageSize"] = image_size
            template["imageBackgroundColor"] = image_background_color
        if title:
            template["title"] = title
        return template
    
    @staticmethod
    def create_action_uri(label: str, uri: str) -> Dict:
        """
        URIアクションを作成
        
        Args:
            label: アクションラベル（最大20文字）
            uri: URI
            
        Returns:
            アクションオブジェクト
        """
        return {
            "type": "uri",
            "label": label,
            "uri": uri
        }
    
    @staticmethod
    def create_action_message(label: str, text: str) -> Dict:
        """
        メッセージアクションを作成
        
        Args:
            label: アクションラベル（最大20文字）
            text: 送信するメッセージテキスト
            
        Returns:
            アクションオブジェクト
        """
        return {
            "type": "message",
            "label": label,
            "text": text
        }
    
    @staticmethod
    def create_action_postback(label: str, data: str, display_text: Optional[str] = None) -> Dict:
        """
        ポストバックアクションを作成
        
        Args:
            label: アクションラベル（最大20文字）
            data: ポストバックデータ（最大300文字）
            display_text: 表示テキスト（オプション、最大300文字）
            
        Returns:
            アクションオブジェクト
        """
        action = {
            "type": "postback",
            "label": label,
            "data": data
        }
        if display_text:
            action["displayText"] = display_text
        return action
    
    def send_text(
        self,
        user_id: str,
        text: str,
        notification_disabled: bool = False
    ) -> Dict:
        """
        テキストメッセージを送信（簡易メソッド）
        
        Args:
            user_id: 送信先ユーザーID
            text: メッセージテキスト
            notification_disabled: 通知を無効にするかどうか
            
        Returns:
            APIレスポンス
        """
        message = self.create_text_message(text)
        return self.push_message(user_id, [message], notification_disabled)
    
    def send_multiple_texts(
        self,
        user_id: str,
        texts: List[str],
        notification_disabled: bool = False
    ) -> Dict:
        """
        複数のテキストメッセージを送信
        
        Args:
            user_id: 送信先ユーザーID
            texts: メッセージテキストのリスト（最大5個）
            notification_disabled: 通知を無効にするかどうか
            
        Returns:
            APIレスポンス
        """
        messages = [self.create_text_message(text) for text in texts[:5]]  # 最大5個
        return self.push_message(user_id, messages, notification_disabled)
    
    def broadcast_message(
        self,
        messages: List[Dict],
        notification_disabled: bool = False
    ) -> Dict:
        """
        ブロードキャストメッセージを送信（友達追加した全員に送信）
        
        Args:
            messages: メッセージオブジェクトのリスト
            notification_disabled: 通知を無効にするかどうか
            
        Returns:
            APIレスポンス
        """
        url = f"{self.BASE_URL}/message/broadcast"
        payload = {
            "messages": messages,
            "notificationDisabled": notification_disabled
        }
        return self._send_request(url, payload)
    
    def send_broadcast_text(
        self,
        text: str,
        notification_disabled: bool = False
    ) -> Dict:
        """
        ブロードキャストテキストメッセージを送信（簡易メソッド）
        友達追加した全員に自動送信（ユーザーID管理不要）
        
        Args:
            text: メッセージテキスト
            notification_disabled: 通知を無効にするかどうか
            
        Returns:
            APIレスポンス
        """
        message = self.create_text_message(text)
        return self.broadcast_message([message], notification_disabled)


# 便利関数（既存コードとの互換性のため）
def send_line_push(token: str, user_id: str, message: str) -> bool:
    """
    LINEプッシュメッセージを送信（既存コードとの互換性のため）
    
    Args:
        token: Channel Access Token
        user_id: ユーザーID
        message: メッセージテキスト
        
    Returns:
        成功した場合True、失敗した場合False
    """
    try:
        api = LinePushAPI(token)
        api.send_text(user_id, message)
        print("LINE通知送信成功")
        return True
    except Exception as e:
        print(f"LINE通知失敗: {e}")
        return False


# コマンドライン実行用
if __name__ == "__main__":
    import sys
    import json
    import argparse
    
    parser = argparse.ArgumentParser(
        description="LINE Push API - プッシュメッセージを送信",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python line_push_api.py "こんにちは！"                    # config.jsonの設定に従う
  python line_push_api.py "チケット販売を検知しました" --silent
  python line_push_api.py メッセージ --no-notification
  python line_push_api.py "全員に送信" --broadcast         # ブロードキャスト送信（設定を上書き）
        """
    )
    parser.add_argument("message", nargs="*", help="送信するメッセージ")
    parser.add_argument(
        "--silent", 
        "--no-notification", 
        action="store_true",
        dest="notification_disabled",
        help="通知音を鳴らさずに送信（サイレント通知）"
    )
    parser.add_argument(
        "--broadcast",
        action="store_true",
        help="ブロードキャスト送信（友達追加した全員に送信、ユーザーID管理不要）"
    )
    
    args = parser.parse_args()
    
    # メッセージが指定されている場合
    if args.message:
        message = " ".join(args.message)
        
        # 設定ファイルから読み込み
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
            
            token = config["line_channel_access_token"]
            
            # メッセージを送信
            api = LinePushAPI(token)
            
            # サイレント通知の設定（オプション > config.json の順で優先）
            if args.notification_disabled:
                notification_disabled = True
            else:
                # config.jsonの設定を確認
                notification_disabled = config.get("notification_disabled", False) or config.get("silent", False)
            
            mode = "（サイレント）" if notification_disabled else ""
            
            if args.broadcast:
                # ブロードキャスト送信（友達追加した全員に送信）
                api.send_broadcast_text(message, notification_disabled=notification_disabled)
                print(f"✓ ブロードキャストメッセージを送信しました{mode}（友達追加した全員に送信）: {message}")
            else:
                # オプションが指定されない場合: config.jsonの設定に従う
                use_broadcast = config.get("use_broadcast", False)
                
                if use_broadcast:
                    # config.jsonでブロードキャストが有効な場合
                    api.send_broadcast_text(message, notification_disabled=notification_disabled)
                    print(f"✓ ブロードキャストメッセージを送信しました{mode}（config.jsonの設定に従い、友達追加した全員に送信）: {message}")
                else:
                    # 従来の方法：ユーザーIDリストを使用
                    user_ids = []
                    # line_user_ids（配列）が設定されている場合はそれを使用
                    if "line_user_ids" in config and isinstance(config["line_user_ids"], list):
                        user_ids = config["line_user_ids"]
                    # line_user_id（単一）が設定されている場合はそれも追加
                    if "line_user_id" in config and config["line_user_id"]:
                        if config["line_user_id"] not in user_ids:
                            user_ids.append(config["line_user_id"])
                    
                    if user_ids:
                        # 複数ユーザーに送信
                        for user_id in user_ids:
                            api.send_text(user_id, message, notification_disabled=notification_disabled)
                        print(f"✓ メッセージを送信しました{mode}（{len(user_ids)}人）: {message}")
                    else:
                        print("エラー: 送信先ユーザーIDが設定されていません")
                        print("以下のいずれかを設定してください:")
                        print("  - config.json に use_broadcast: true を設定")
                        print("  - config.json に line_user_id または line_user_ids を設定")
                        print("  - --broadcast オプションを指定")
                        sys.exit(1)
        except FileNotFoundError:
            print("エラー: config.json が見つかりません")
            sys.exit(1)
        except KeyError as e:
            print(f"エラー: config.json に必要な設定がありません: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"エラー: {e}")
            sys.exit(1)
    else:
        # 引数がない場合はヘルプを表示
        parser.print_help()
        print()
        print("---")
        print("テスト実行:")
        
        # 設定ファイルから読み込み
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
            
            token = config["line_channel_access_token"]
            
            # APIクライアントの作成
            api = LinePushAPI(token)
            
            # テストメッセージ（config.jsonの設定に従う）
            print("テストメッセージを送信...")
            use_broadcast = config.get("use_broadcast", False)
            
            if use_broadcast:
                api.send_broadcast_text("これはテストメッセージです。")
                print("✓ ブロードキャスト送信完了（友達追加した全員に送信）")
            else:
                user_ids = []
                if "line_user_ids" in config and isinstance(config["line_user_ids"], list):
                    user_ids = config["line_user_ids"]
                if "line_user_id" in config and config["line_user_id"]:
                    if config["line_user_id"] not in user_ids:
                        user_ids.append(config["line_user_id"])
                
                if user_ids:
                    for user_id in user_ids:
                        api.send_text(user_id, "これはテストメッセージです。")
                    print(f"✓ 送信完了（{len(user_ids)}人）")
                else:
                    print("エラー: 送信先ユーザーIDが設定されていません")
        except Exception as e:
            print(f"エラー: {e}")
