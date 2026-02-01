import nodriver as uc


async def get_driver(headless=True):
    # nodriver doesn't use the same options structure, but we can pass args
    browser_args = []
    if headless:
        browser_args.append("--headless=new")
    browser_args.append("--window-size=1300,700")

    driver = await uc.start(
        headless=headless,
        browser_args=browser_args
    )
    
    # Set window size if not headless (or even if headless, though less relevant)
    # nodriver doesn't have a direct set_window_size on the browser object easily accessible 
    # in the same way, but we can do it via CDP if needed. 
    # For now, relying on the start arg.
    
    return driver