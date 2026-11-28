"""코랩의 기본 전용 링크와 선택적인 공개 공유 링크."""
import html
import urllib.error
import urllib.request


def private_link(server):
    from google.colab import output
    base = output.eval_js(f'google.colab.kernel.proxyPort({server.server_port})')
    return base.rstrip('/') + '/?key=' + server.access_token


def public_link(server):
    """Gradio 공유 터널로 같은 대시보드 서버를 연결한다.

    패키지 설치는 호출자가 Colab에서만 수행한다. 터널은 런타임과 함께 종료된다.
    """
    import gradio as gr
    from fastapi import Request
    from starlette.responses import Response
    with gr.Blocks(analytics_enabled=False) as demo:
        gr.Markdown('PM System 대시보드 · 코랩 출력의 전용 접속 링크를 사용하세요.')
    demo.launch(share=True, inline=False, prevent_thread_lock=True, quiet=True,
                show_api=False)

    async def proxy(request: Request, path: str = ''):
        # 동기 파일 저장/요청은 이벤트 루프 바깥에서 수행한다.
        import asyncio
        body = await request.body()
        if len(body) > 2_000_000:
            return Response('요청 크기 초과', status_code=413)
        def forward():
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *_):
                    return None
            query = request.url.query
            target = f'http://127.0.0.1:{server.server_port}/' + path
            if query:
                target += '?' + query
            headers = {k: request.headers[k] for k in ('cookie','content-type') if k in request.headers}
            req = urllib.request.Request(target, data=body if request.method == 'POST' else None,
                                         method=request.method, headers=headers)
            try:
                response = urllib.request.build_opener(NoRedirect).open(req, timeout=20)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                data = response.read()
                allowed = ('content-type','set-cookie','location','content-disposition','cache-control')
                out = {k: v for k, v in response.headers.items() if k.lower() in allowed}
                return Response(data, status_code=response.code, headers=out)
        return await asyncio.to_thread(forward)

    demo.app.add_api_route('/dashboard/', proxy, methods=['GET','POST'])
    demo.app.add_api_route('/dashboard/{path:path}', proxy, methods=['GET','POST'])
    if not demo.share_url:
        demo.close()
        raise RuntimeError('공개 터널을 만들지 못했습니다. 코랩 전용 링크를 사용하세요.')
    return demo, demo.share_url.rstrip('/') + '/dashboard/?key=' + server.access_token


def show_link(url, label):
    from IPython.display import HTML, display
    display(HTML(f'<p><a target="_blank" rel="noopener" href="{html.escape(url, quote=True)}" '
                 'style="display:inline-block;padding:14px 22px;background:#1b303d;color:white;'
                 f'border-radius:9px;text-decoration:none">{html.escape(label)}</a></p>'))
