export function ApiKeyGuide({
  marketplace
}: {
  marketplace: 'wildberries' | 'ozon'
}) {
  return (
    <details className='api-key-guide'>
      <summary>Как создать API-ключ</summary>
      {marketplace === 'ozon' ? (
        <>
          <ol>
            <li>В Ozon Seller откройте «Настройки → Seller API».</li>
            <li>
              Создайте ключ для чтения товаров, аналитики, финансов, остатков и
              поставок.
            </li>
            <li>Скопируйте Client ID и API Key в поля формы.</li>
          </ol>
          <a
            href='https://dev.ozon.ru/start/301-Kak-sgenerirovat-kliuch-dlia-Seller-API/'
            target='_blank'
            rel='noreferrer'
          >
            Инструкция Ozon
          </a>
        </>
      ) : (
        <>
          <ol>
            <li>
              В WB Partners откройте профиль → «Интеграции по API» → «Создать
              токен».
            </li>
            <li>
              Для подключения сервиса выберите PERK в каталоге интеграций, если
              он доступен. Для локального теста собственного магазина — токен
              для своей интеграции.
            </li>
            <li>
              Выберите категории: Контент, Аналитика, Статистика, Цены и скидки,
              Маркетплейс, Финансы, Поставки. Достаточно доступа на чтение.
            </li>
            <li>Скопируйте токен в форму подключения.</li>
          </ol>
          <a
            href='https://seller.wildberries.ru/instructions/material/A-1155'
            target='_blank'
            rel='noreferrer'
          >
            Инструкция Wildberries
          </a>
        </>
      )}
    </details>
  )
}
